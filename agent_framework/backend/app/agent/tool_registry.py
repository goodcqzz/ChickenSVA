"""
工具注册与执行框架

提供：
- 工具注册中心
- 工具定义管理
- 工具执行调度
- 自动转换为 LLM Function Calling 格式
- 前端事件通知（workspace_activate 等）
"""

import asyncio
import inspect
import logging
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable, Awaitable, Dict, List, Optional

from app.llm.base import ToolDefinition as LLMToolDefinition
from app.tools.data import (
    analyze_breed_association,
    genome_wide_association_scan,
    get_database_info,
    query_annotation,
    query_breed_profile,
    query_sv,
)
from app.tools.imputation import (
    create_imputation_workspace,
    get_workspace_status,
    request_file_upload,
    run_workspace_imputation,
    validate_workspace_files,
)
from app.tools.knowledge import query_literature_kb

logger = logging.getLogger(__name__)


@dataclass
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[str]] = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: List[ToolParameter]
    handler: Callable[..., Awaitable[Dict[str, Any]]]
    category: str = "general"

    def to_llm_tool(self) -> LLMToolDefinition:
        properties: Dict[str, Any] = {}
        required: List[str] = []

        for param in self.parameters:
            prop: Dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.default is not None:
                prop["default"] = param.default
            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return LLMToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": properties,
                "required": required,
            },
        )


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._on_event: Optional[Callable[..., Awaitable[None]]] = None

    def set_event_callback(self, callback: Callable[..., Awaitable[None]]):
        self._on_event = callback

    async def emit_event(self, event_type: str, payload: Dict[str, Any], session_id: Optional[str] = None):
        if self._on_event:
            await self._on_event(event_type, payload, session_id)

    def register(
        self,
        name: str,
        description: str,
        parameters: List[ToolParameter],
        handler: Callable[..., Awaitable[Dict[str, Any]]],
        category: str = "general",
    ) -> None:
        tool = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            category=category,
        )
        self._tools[name] = tool
        logger.info(f"注册工具: {name} [{category}]")

    def register_tool(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool
        logger.info(f"注册工具: {tool.name} [{tool.category}]")

    def unregister(self, name: str) -> None:
        if name in self._tools:
            del self._tools[name]
            logger.info(f"注销工具: {name}")

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def get_all_tools(self) -> List[ToolDefinition]:
        return list(self._tools.values())

    def get_tools_by_category(self, category: str) -> List[ToolDefinition]:
        return [t for t in self._tools.values() if t.category == category]

    def get_llm_tool_definitions(self) -> List[LLMToolDefinition]:
        return [tool.to_llm_tool() for tool in self._tools.values()]

    async def execute(self, tool_name: str, arguments: Dict[str, Any], session_id: Optional[str] = None) -> Dict[str, Any]:
        tool = self._tools.get(tool_name)
        if not tool:
            logger.error(f"工具不存在: {tool_name}")
            return {
                "error": f"工具不存在: {tool_name}",
                "available_tools": list(self._tools.keys()),
            }

        try:
            logger.info(f"执行工具: {tool_name}, 参数: {arguments}")
            call_args = dict(arguments)
            if session_id:
                sig = inspect.signature(tool.handler)
                if "session_id" in sig.parameters:
                    call_args["session_id"] = session_id
            result = await tool.handler(**call_args)
            logger.info(f"工具执行完成: {tool_name}")
            return result
        except TypeError as e:
            logger.error(f"工具参数错误 [{tool_name}]: {e}")
            return {"error": f"参数错误: {str(e)}"}
        except Exception as e:
            logger.error(f"工具执行失败 [{tool_name}]: {e}")
            return {"error": f"执行失败: {str(e)}"}

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def tool_names(self) -> List[str]:
        return list(self._tools.keys())


# 全局工具注册表单例
_default_registry_instance: Optional[ToolRegistry] = None


def create_default_registry() -> ToolRegistry:
    """获取或创建默认工具注册表（单例模式）"""
    global _default_registry_instance
    if _default_registry_instance is not None:
        return _default_registry_instance

    registry = ToolRegistry()

    # ========== 数据查询工具 ==========

    registry.register(
        name="get_database_info",
        description="获取鸡基因组SV数据库的元信息，包括样本数、变异数、支持的SV类型、品种列表等",
        parameters=[
            ToolParameter(name="info_type", type="string", description="信息类型: overview(概览), breeds(品种列表), stats(统计信息), samples(样本信息)", required=False, default="overview", enum=["overview", "breeds", "stats", "samples"]),
        ],
        handler=get_database_info,
        category="data_query",
    )

    registry.register(
        name="query_breed_profile",
        description="查询鸡品种的表型信息，包括生产性能、形态特征等",
        parameters=[
            ToolParameter(name="breed_name", type="string", description="品种名称，如'白来航鸡'、'丝羽乌骨鸡'", required=True),
            ToolParameter(name="trait", type="string", description="关注的表型特征，可选", required=False),
        ],
        handler=query_breed_profile,
        category="data_query",
    )

    registry.register(
        name="query_sv",
        description="查询结构变异(SV)数据，支持按基因名、基因组区域或变异ID查询",
        parameters=[
            ToolParameter(name="query_type", type="string", description="查询类型: gene(基因名), region(基因组区域), id(变异ID)", required=True, enum=["gene", "region", "id"]),
            ToolParameter(name="query_value", type="string", description="查询值，如基因名(BRCA1)、区域(chr1:1000000-2000000)或变异ID", required=True),
            ToolParameter(name="sample_filter", type="string", description="样本筛选条件，可选", required=False),
            ToolParameter(name="sv_type", type="string", description="SV类型筛选: DEL,DUP,INV,INS,BND", required=False),
            ToolParameter(name="limit", type="integer", description="返回结果数量限制", required=False, default=20),
        ],
        handler=query_sv,
        category="data_query",
    )

    registry.register(
        name="query_annotation",
        description="查询基因或变异的功能注释信息，包括GO功能、KEGG通路、GWAS关联等",
        parameters=[
            ToolParameter(name="gene_name", type="string", description="基因名称", required=False),
            ToolParameter(name="sv_id", type="string", description="变异ID", required=False),
            ToolParameter(name="annotation_type", type="string", description="注释类型: all,function,pathway,phenotype", required=False, default="all", enum=["all", "function", "pathway", "phenotype"]),
        ],
        handler=query_annotation,
        category="data_query",
    )

    registry.register(
        name="analyze_breed_association",
        description="执行品种层表型-基因型关联分析，支持位点级 sv_trait、表型概览和旧版 breed/trait 摘要",
        parameters=[
            ToolParameter(name="analysis_type", type="string", description="分析类型: phenotype_overview, sv_trait, breed_trait, gene_trait, gene_summary_trait, region_trait", required=False, default="sv_trait", enum=["phenotype_overview", "sv_trait", "breed_trait", "gene_trait", "gene_summary_trait", "region_trait"]),
            ToolParameter(name="breed", type="string", description="品种名称或兼容的SV ID", required=False),
            ToolParameter(name="trait", type="string", description="表型特征", required=False),
            ToolParameter(name="phenotype_name", type="string", description="表型原名，如 平均体重(Body_size_g)", required=False),
            ToolParameter(name="sv_id", type="string", description="SV ID", required=False),
            ToolParameter(name="sv_ids", type="string", description="SV ID 列表（逗号分隔）", required=False),
            ToolParameter(name="genes", type="string", description="基因列表（逗号分隔）", required=False),
            ToolParameter(name="chromosome", type="string", description="染色体编号", required=False),
            ToolParameter(name="start_pos", type="integer", description="起始位置", required=False),
            ToolParameter(name="end_pos", type="integer", description="结束位置", required=False),
            ToolParameter(name="window", type="integer", description="窗口大小(bp)", required=False),
            ToolParameter(name="method", type="string", description="相关方法: auto, pearson, spearman, weighted_pearson, weighted_spearman", required=False, default="auto"),
            ToolParameter(name="aggregate_method", type="string", description="聚合方式: mean, max, sum", required=False, default="mean"),
            ToolParameter(name="covariate_mode", type="string", description="协变量模式: none, adjust, stratify", required=False, default="none"),
            ToolParameter(name="p_threshold", type="number", description="显著性阈值", required=False, default=0.05),
            ToolParameter(name="permutations", type="integer", description="置换检验次数", required=False, default=200),
            ToolParameter(name="sv_type", type="string", description="SV类型筛选，可选", required=False),
        ],
        handler=analyze_breed_association,
        category="data_query",
    )

    registry.register(
        name="query_literature_kb",
        description=(
            "检索 Dify 期刊文献知识库（中文父子QA、中文纯QA、英文QA）。"
            "仅在用户明确需要文献证据、方法学背景、品种历史/特征描述或基因生物学解释时调用；"
            "SV/频率/注释/关联/GWAS/填充等结构化数据问题禁止调用。"
        ),
        parameters=[
            ToolParameter(name="query", type="string", description="检索问题，如「鸡 结构变异 GWAS」", required=True),
            ToolParameter(
                name="dataset",
                type="string",
                description="知识库：auto(三库)/parent_qa/pure_qa/english_qa 或 dataset UUID",
                required=False,
                default="auto",
            ),
            ToolParameter(name="top_k", type="integer", description="返回条数", required=False, default=5),
            ToolParameter(
                name="search_method",
                type="string",
                description="hybrid_search | full_text_search | semantic_search",
                required=False,
            ),
        ],
        handler=query_literature_kb,
        category="knowledge",
    )

    registry.register(
        name="genome_wide_association_scan",
        description="执行全基因组SV-表型关联扫描，返回按显著性和相关强度排序的候选位点",
        parameters=[
            ToolParameter(name="phenotype_name", type="string", description="表型名称，如 平均体重(Body_size_g)", required=True),
            ToolParameter(name="method", type="string", description="相关方法: auto, pearson, spearman, weighted_pearson, weighted_spearman", required=False, default="auto"),
            ToolParameter(name="covariate_mode", type="string", description="协变量模式: none, adjust, stratify", required=False, default="none"),
            ToolParameter(name="categorical_covariates", type="array", description="分类协变量列表", required=False),
            ToolParameter(name="numeric_covariates", type="array", description="数值协变量列表", required=False),
            ToolParameter(name="stratify_by", type="array", description="分层字段列表", required=False),
            ToolParameter(name="min_breeds", type="integer", description="最少纳入品种数", required=False, default=8),
            ToolParameter(name="min_stratum_breeds", type="integer", description="分层模式下每层最少品种数", required=False, default=4),
            ToolParameter(name="database_name", type="string", description="指定数据库名称", required=False),
            ToolParameter(name="search_all_databases", type="boolean", description="是否搜索所有数据库", required=False, default=False),
            ToolParameter(name="sv_type", type="string", description="SV类型筛选: DEL 或 INS", required=False),
            ToolParameter(name="chromosomes", type="array", description="染色体列表", required=False),
            ToolParameter(name="include_annotation", type="boolean", description="是否补充基因注释", required=False, default=False),
            ToolParameter(name="top_n", type="integer", description="返回前N个候选", required=False, default=20),
            ToolParameter(name="rank_by", type="string", description="排序字段: p_value, fdr, correlation, abs_correlation", required=False, default="p_value"),
            ToolParameter(name="sort_order", type="string", description="排序方向: asc 或 desc", required=False, default="asc"),
            ToolParameter(name="min_abs_correlation", type="number", description="最小绝对相关系数阈值", required=False),
        ],
        handler=genome_wide_association_scan,
        category="data_query",
    )

    # ========== 数据填充工具 ==========

    registry.register(
        name="create_imputation_workspace",
        description="为当前对话创建或复用唯一的数据填充工作区（一个对话对应一个工作区）。",
        parameters=[
            ToolParameter(name="workspace_type", type="string", description="工作区类型", required=False, default="imputation", enum=["imputation", "query"]),
            ToolParameter(name="description", type="string", description="工作区描述", required=False),
        ],
        handler=partial(create_imputation_workspace, registry),
        category="imputation",
    )

    registry.register(
        name="request_file_upload",
        description="【关键工具】触发前端工作区面板显示文件上传界面。创建工作区后必须调用此工具，用户才能在前端看到上传区域。",
        parameters=[
            ToolParameter(name="workspace_id", type="string", description="工作区ID（由create_imputation_workspace返回）", required=True),
            ToolParameter(name="file_types", type="string", description="接受的文件类型，逗号分隔", required=False, default="vcf,plink"),
            ToolParameter(name="max_size_mb", type="integer", description="最大文件大小(MB)", required=False, default=5),
        ],
        handler=partial(request_file_upload, registry),
        category="imputation",
    )

    registry.register(
        name="validate_workspace_files",
        description="验证工作区中已上传文件的格式和完整性",
        parameters=[
            ToolParameter(name="workspace_id", type="string", description="工作区ID", required=True),
            ToolParameter(name="file_names", type="string", description="指定验证的文件名，逗号分隔（空则验证全部）", required=False),
        ],
        handler=validate_workspace_files,
        category="imputation",
    )

    registry.register(
        name="run_workspace_imputation",
        description="在工作区中执行基因型填充(beagle)，需要先上传并验证数据文件",
        parameters=[
            ToolParameter(name="workspace_id", type="string", description="工作区ID", required=True),
            ToolParameter(name="input_file", type="string", description="输入文件名", required=False),
            ToolParameter(name="ref_panel", type="string", description="参考面板", required=False, default="default"),
            ToolParameter(name="nthreads", type="integer", description="线程数", required=False, default=4),
        ],
        handler=partial(run_workspace_imputation, registry),
        category="imputation",
    )

    registry.register(
        name="get_workspace_status",
        description="获取工作区当前状态，包括文件列表、任务进度等",
        parameters=[
            ToolParameter(name="workspace_id", type="string", description="工作区ID", required=True),
        ],
        handler=get_workspace_status,
        category="imputation",
    )

    # 保存到全局变量（单例模式）
    _default_registry_instance = registry

    return registry
