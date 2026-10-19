#!/usr/bin/env python3
"""
鸡基因组 SV 数据库 - MCP HTTP 服务器 (扩展版)
新增：基因型填充工具、文件上传端点
"""

from flask import Flask, request, Response, jsonify, send_file
from flask_cors import CORS
import json
import logging
import os
import hashlib
import uuid
from typing import Any, Dict, List
import asyncio
from functools import wraps
from datetime import datetime, timezone

# 导入原有工具
from chicken_sv_tool import ChickenSVTool
from async_task_manager import AsyncTaskManager
from imputation_tool import get_imputation_tool
from imputation_workspace import get_workspace_manager

# 导入新增组件（用于解决Dify工具调用循环问题）
from tool_governor import ToolCallGovernor, tool_governor
from conversation_manager import ConversationStateManager, conversation_manager

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('mcp_http_server')

BACKEND_URL = os.environ.get("CHICKENSV_BACKEND_URL", "http://127.0.0.1:9801")
DEFAULT_MCP_PORT = int(os.environ.get("CHICKENSV_MCP_PORT", "9802"))
MCP_HOST = os.environ.get("CHICKENSV_MCP_HOST", "127.0.0.1")
MCP_CORS_ORIGINS = os.environ.get(
    "CHICKENSV_MCP_CORS_ORIGINS",
    "http://127.0.0.1:9800,http://localhost:9800,http://127.0.0.1:5173,http://localhost:5173"
)

app = Flask(__name__)
_cors_origins = [o.strip() for o in MCP_CORS_ORIGINS.split(",") if o.strip()]
if _cors_origins:
    CORS(app, origins=_cors_origins)
else:
    CORS(app)

# 初始化工具
annotation_path = '../annotation/Gallus_gallus.bGalGal1.mat.broiler.GRCg7b.115.gff3'
tool = ChickenSVTool(
    data_path='../data',
    annotation_path=annotation_path if os.path.exists(annotation_path) else None
)

# 初始化填充工具
imputation_tool = get_imputation_tool()

# 初始化工作区管理器
workspace_manager = get_workspace_manager()

SERVER_INFO = {
    "name": "chicken-sv-database",
    "version": "3.1.0",
    "description": "鸡基因组结构变异数据库、表型库直查、注释、全基因组扫描、品种层协变量关联分析、增强型 JSON DSL 与异步任务执行、基因型填充服务",
    "protocolVersion": "2024-11-05"
}

# 全局状态存储：用于前端轮询获取待处理的上传请求
_pending_upload_requests = {}


def store_upload_request(workspace_id: str, session_id: str = None):
    """存储上传请求，供前端轮询获取"""
    request_id = str(uuid.uuid4())
    _pending_upload_requests[request_id] = {
        'workspace_id': workspace_id,
        'session_id': session_id,
        'created_at': _utc_now_iso(),
        'status': 'pending'
    }
    # 清理5分钟前的请求
    _cleanup_old_requests()
    return request_id


def _cleanup_old_requests():
    """清理过期的上传请求"""
    now = datetime.now(timezone.utc)
    expired_keys = []
    for req_id, req in _pending_upload_requests.items():
        created = datetime.fromisoformat(req['created_at'].replace('Z', '+00:00'))
        if (now - created).total_seconds() > 300:  # 5分钟过期
            expired_keys.append(req_id)
    for key in expired_keys:
        del _pending_upload_requests[key]


def get_pending_upload_requests(session_id: str = None):
    """获取待处理的上传请求"""
    _cleanup_old_requests()
    if session_id:
        return [req for req in _pending_upload_requests.values() if req.get('session_id') == session_id]
    return list(_pending_upload_requests.values())


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_data_version() -> str:
    """Compute a lightweight data fingerprint from file stats for traceability."""
    hasher = hashlib.sha256()
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate_dirs = [
        os.path.join(root_dir, 'data'),
        os.path.join(root_dir, 'annotation'),
        os.path.join(root_dir, 'refpanel'),
    ]
    candidates: List[str] = []
    for directory in candidate_dirs:
        if not os.path.isdir(directory):
            continue
        for current_root, _, files in os.walk(directory):
            for file_name in sorted(files):
                if not (file_name.endswith('.csv') or file_name.endswith('.gff3') or file_name.endswith('.vcf.gz')):
                    continue
                candidates.append(os.path.join(current_root, file_name))

    for file_path in sorted(candidates):
        try:
            stat = os.stat(file_path)
            rel = os.path.relpath(file_path, root_dir)
            line = f"{rel}|{int(stat.st_size)}|{int(stat.st_mtime)}\n"
            hasher.update(line.encode('utf-8'))
        except OSError:
            continue
    return hasher.hexdigest()[:16] if candidates else 'no-data'


DATA_VERSION = _compute_data_version()
TASK_MANAGER = AsyncTaskManager(worker_count=int(os.getenv('MCP_TASK_WORKERS', '2')))


def async_to_sync(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(f(*args, **kwargs))
        finally:
            loop.close()
    return wrapper


# ==================== 工具 Schema ====================

def get_tool_schema() -> List[Dict[str, Any]]:
    """核心工具的 Schema 定义（包含原有工具和新增工具）"""
    return [
        # ===== 原有工具 =====
        {
            "name": "get_database_info",
            "description": "获取SV数据库、品种列和表型矩阵的元信息。包括数据库列表、字段结构、统计概览、品种列表和表型列表。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "info_type": {
                        "type": "string",
                        "enum": ["overview", "databases", "structure", "statistics", "breeds", "phenotypes"],
                        "description": "信息类型：overview(总览) / databases(列表) / structure(结构) / statistics(统计) / breeds(品种) / phenotypes(表型)",
                        "default": "overview"
                    },
                    "database_name": {
                        "type": "string",
                        "description": "指定数据库名称（可选）"
                    }
                }
            }
        },
        {
            "name": "query_breed_profile",
            "description": "按品种名、标签或模糊片段直查表型库，返回品种特征、坐标、气候和颜色等知识库信息。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "breed_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要查询的品种名或标签别名列表，例如 固始鸡、茶花鸡、HGS"
                    },
                    "breeds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "breed_names 的兼容别名字段"
                    },
                    "exact_match": {
                        "type": "boolean",
                        "default": False,
                        "description": "是否只做精确匹配"
                    },
                    "include_trait_values": {
                        "type": "boolean",
                        "default": True,
                        "description": "是否返回完整 trait_values 原始表型值"
                    },
                    "max_results": {
                        "type": "integer",
                        "default": 20,
                        "description": "最大返回匹配数"
                    }
                },
                "required": ["breed_names"]
            }
        },
        {
            "name": "query_sv",
            "description": """查询SV结构变异数据（核心工具）。支持4种查询方式，支持批量查询和窗口范围搜索。
- gene: 按基因名查询，支持批量和上下游窗口（如±50kb）
- region: 按染色体区域查询，支持批量
- id: 按SV ID查询，支持批量
- filter: 自定义筛选条件""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query_type": {"type": "string", "enum": ["gene", "region", "id", "filter"], "description": "查询方式"},
                    "genes": {"type": "array", "items": {"type": "string"}, "description": "基因名列表（gene查询）"},
                    "window": {"type": "integer", "default": 0, "description": "上下游窗口大小(bp)"},
                    "upstream": {"type": "integer", "description": "上游窗口(bp)，优先于window"},
                    "downstream": {"type": "integer", "description": "下游窗口(bp)，优先于window"},
                    "regions": {"type": "array", "items": {"type": "object"}, "description": "区域列表（region查询）"},
                    "chromosome": {"type": "string", "description": "染色体编号"},
                    "start_pos": {"type": "integer", "description": "起始位置"},
                    "end_pos": {"type": "integer", "description": "结束位置"},
                    "sv_ids": {"type": "array", "items": {"type": "string"}, "description": "SV ID列表（id查询）"},
                    "filters": {"type": "array", "items": {"type": "object"}, "description": "筛选条件列表（filter查询）"},
                    "sv_type": {"type": "string", "enum": ["DEL", "INS"], "description": "SV类型筛选"},
                    "breeds": {"type": "array", "items": {"type": "string"}, "description": "指定返回频率的品种列表，支持模糊匹配"},
                    "include_all_breeds": {"type": "boolean", "default": False, "description": "是否返回所有品种频率"},
                    "database_name": {"type": "string", "description": "指定数据库"},
                    "search_all_databases": {"type": "boolean", "default": False, "description": "搜索所有数据库"},
                    "include_annotation": {"type": "boolean", "default": True, "description": "包含基因注释"},
                    "max_results": {"type": "integer", "default": 100, "description": "最大返回数"}
                },
                "required": ["query_type"]
            }
        },
        {
            "name": "query_annotation",
            "description": """查询基因组注释信息。支持3种查询方式。
- search: 按基因名/ID搜索，支持批量和模糊搜索
- region: 查询区域内的基因
- position: 位置注释，查看某位置是否在基因内""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query_type": {"type": "string", "enum": ["search", "region", "position"], "description": "查询方式"},
                    "queries": {"type": "array", "items": {"type": "string"}, "description": "基因名/ID列表（search查询）"},
                    "exact_match": {"type": "boolean", "default": False, "description": "精确匹配"},
                    "regions": {"type": "array", "items": {"type": "object"}, "description": "区域列表（region查询）"},
                    "chromosome": {"type": "string", "description": "染色体编号"},
                    "start_pos": {"type": "integer", "description": "起始位置"},
                    "end_pos": {"type": "integer", "description": "结束位置"},
                    "positions": {"type": "array", "items": {"type": "object"}, "description": "位置列表（position查询）"},
                    "max_results": {"type": "integer", "default": 50, "description": "最大返回数"}
                },
                "required": ["query_type"]
            }
        },
        {
            "name": "analyze_breed_association",
            "description": "进行品种层表型-基因型关联分析。适用于品种聚合频率与品种表型的候选发现，不适用于个体级因果推断。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "analysis_type": {
                        "type": "string",
                        "enum": ["phenotype_overview", "sv_trait", "gene_trait", "gene_summary_trait", "region_trait"],
                        "description": "分析类型：phenotype_overview(表型概览) / sv_trait(指定SV) / gene_trait(位点级基因窗口) / gene_summary_trait(基因级聚合) / region_trait(区域)"
                    },
                    "phenotype_name": {"type": "string", "description": "数值型表型名称，如 平均体重(Body_size_g)、Bio12、海拔高度(Elevation)"},
                    "genes": {"type": "array", "items": {"type": "string"}, "description": "基因列表（gene_trait）"},
                    "window": {"type": "integer", "default": 0, "description": "基因窗口大小(bp)"},
                    "upstream": {"type": "integer", "description": "上游窗口(bp)"},
                    "downstream": {"type": "integer", "description": "下游窗口(bp)"},
                    "regions": {"type": "array", "items": {"type": "object"}, "description": "区域列表（region_trait）"},
                    "chromosome": {"type": "string", "description": "染色体编号"},
                    "start_pos": {"type": "integer", "description": "起始位置"},
                    "end_pos": {"type": "integer", "description": "结束位置"},
                    "sv_ids": {"type": "array", "items": {"type": "string"}, "description": "SV ID 列表（sv_trait）"},
                    "sv_type": {"type": "string", "enum": ["DEL", "INS"], "description": "SV类型筛选"},
                    "method": {"type": "string", "enum": ["auto", "pearson", "spearman", "weighted_pearson", "weighted_spearman"], "default": "auto", "description": "相关分析方法"},
                    "aggregate_method": {"type": "string", "enum": ["mean", "max", "sum"], "default": "mean", "description": "gene_summary_trait 下的基因窗口聚合方式"},
                    "covariate_mode": {"type": "string", "enum": ["none", "adjust", "stratify"], "default": "none", "description": "协变量控制模式：none(不控制) / adjust(回归校正) / stratify(分层控制)"},
                    "categorical_covariates": {"type": "array", "items": {"type": "string"}, "description": "分类协变量列表，如 大分类、细分"},
                    "numeric_covariates": {"type": "array", "items": {"type": "string"}, "description": "数值协变量列表，如 纬度、经度"},
                    "stratify_by": {"type": "array", "items": {"type": "string"}, "description": "分层字段列表，如 大分类、细分"},
                    "min_breeds": {"type": "integer", "default": 8, "description": "最少纳入品种数"},
                    "min_stratum_breeds": {"type": "integer", "default": 4, "description": "分层模式下每层最少品种数"},
                    "max_variants": {"type": "integer", "default": 100, "description": "最多评估的候选位点数"},
                    "top_n": {"type": "integer", "default": 20, "description": "返回前N个关联结果"},
                    "permutations": {"type": "integer", "default": 200, "description": "置换检验次数，0表示不计算P值"},
                    "random_seed": {"type": "integer", "default": 42, "description": "随机种子"},
                    "database_name": {"type": "string", "description": "指定数据库"},
                    "search_all_databases": {"type": "boolean", "default": False, "description": "搜索所有数据库"},
                    "include_annotation": {"type": "boolean", "default": True, "description": "是否返回基因注释"}
                },
                "required": ["analysis_type"]
            }
        },
        {
            "name": "run_analysis_task",
            "description": "执行受限 JSON DSL 分析任务。支持白名单工具多步串联、$ref 引用、条件分支以及结果排序/投影/裁剪。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_name": {
                        "type": "string",
                        "description": "任务名称",
                        "default": "analysis_task"
                    },
                    "description": {
                        "type": "string",
                        "description": "任务描述"
                    },
                    "stop_on_error": {
                        "type": "boolean",
                        "default": True,
                        "description": "步骤失败时是否立即停止"
                    },
                    "steps": {
                        "type": "array",
                        "description": "任务步骤列表。每一步包含 id、tool、arguments，可选 when 条件和 transform 结果变换。arguments/when/transform 内支持 {\"$ref\": \"step_id.path.to.value\"} 引用前一步输出。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "步骤 ID，供后续 $ref 引用"},
                                "tool": {
                                    "type": "string",
                                    "enum": ["get_database_info", "query_breed_profile", "query_sv", "query_annotation", "analyze_breed_association", "genome_wide_association_scan"],
                                    "description": "步骤使用的白名单工具"
                                },
                                "arguments": {
                                    "type": "object",
                                    "description": "工具参数对象，支持嵌套 $ref"
                                },
                                "when": {
                                    "type": ["object", "boolean"],
                                    "description": "步骤条件。支持 left/right/op 形式，也支持 all/any/not 组合。"
                                },
                                "transform": {
                                    "type": "object",
                                    "description": "步骤结果变换。支持 path、sort、offset、limit、project。"
                                }
                            },
                            "required": ["tool"]
                        }
                    }
                },
                "required": ["steps"]
            }
        },
        {
            "name": "genome_wide_association_scan",
            "description": "对全基因组或指定染色体范围内的 SV 位点进行品种层表型相关扫描，返回按 P 值/FDR/相关强度排序的 topN 候选。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "phenotype_name": {"type": "string", "description": "数值型表型名称，如 平均体重(Body_size_g)"},
                    "method": {"type": "string", "enum": ["auto", "pearson", "spearman", "weighted_pearson", "weighted_spearman"], "default": "auto", "description": "相关分析方法"},
                    "covariate_mode": {"type": "string", "enum": ["none", "adjust", "stratify"], "default": "none", "description": "协变量控制模式"},
                    "categorical_covariates": {"type": "array", "items": {"type": "string"}, "description": "分类协变量列表"},
                    "numeric_covariates": {"type": "array", "items": {"type": "string"}, "description": "数值协变量列表"},
                    "stratify_by": {"type": "array", "items": {"type": "string"}, "description": "分层字段列表"},
                    "min_breeds": {"type": "integer", "default": 8, "description": "最少纳入品种数"},
                    "min_stratum_breeds": {"type": "integer", "default": 4, "description": "分层模式下每层最少品种数"},
                    "database_name": {"type": "string", "description": "指定数据库"},
                    "search_all_databases": {"type": "boolean", "default": False, "description": "是否扫描所有数据库"},
                    "sv_type": {"type": "string", "enum": ["DEL", "INS"], "description": "SV 类型筛选"},
                    "chromosomes": {"type": "array", "items": {"type": "string"}, "description": "指定染色体列表，不传则扫描全基因组"},
                    "include_annotation": {"type": "boolean", "default": True, "description": "是否补充基因注释"},
                    "top_n": {"type": "integer", "default": 20, "description": "返回前 N 个候选"},
                    "rank_by": {"type": "string", "enum": ["p_value", "fdr", "correlation", "abs_correlation"], "default": "p_value", "description": "排序字段"},
                    "sort_order": {"type": "string", "enum": ["asc", "desc"], "default": "asc", "description": "排序方向"},
                    "min_abs_correlation": {"type": "number", "description": "最小绝对相关系数阈值"}
                },
                "required": ["phenotype_name"]
            }
        },
        # ===== 新增工具：AI引导式数据填充工作流 =====
        {
            "name": "create_imputation_workspace",
            "description": """创建基因型填充专用工作区。
当用户需要进行数据填充时，首先调用此工具创建工作区，系统会自动创建标准化的目录结构。
工作区创建后，返回工作区ID和目录信息，供后续步骤使用。""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "output_path": {
                        "type": "string",
                        "description": "用户指定的输出目录路径（可选，默认使用系统目录）"
                    },
                    "description": {
                        "type": "string",
                        "description": "工作区描述信息"
                    }
                }
            }
        },
        {
            "name": "validate_workspace_files",
            "description": """校验工作区中的输入文件格式。
在用户上传文件后调用此工具，系统会自动检测文件格式（VCF/PLINK）并进行完整性校验。
返回详细的校验报告，包括文件格式、样本数、变异数等信息。""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "workspace_id": {
                        "type": "string",
                        "description": "工作区ID"
                    }
                },
                "required": ["workspace_id"]
            }
        },
        {
            "name": "convert_workspace_files",
            "description": """转换工作区中的文件格式。
如果输入文件是PLINK格式（.bed/.bim/.fam），调用此工具将其转换为VCF格式，以便进行基因型填充。
自动处理格式转换、压缩和索引创建。""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "workspace_id": {
                        "type": "string",
                        "description": "工作区ID"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "输出文件名前缀（可选）"
                    }
                },
                "required": ["workspace_id"]
            }
        },
        {
            "name": "run_workspace_imputation",
            "description": """在工作区中执行基因型填充。
在工作区准备好VCF文件后调用此工具执行填充操作。系统会自动选择合适的输入文件（原始VCF或转换后的VCF），
执行beagle填充，并将结果保存到工作区的output目录。""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "workspace_id": {
                        "type": "string",
                        "description": "工作区ID"
                    },
                    "ref_panel": {
                        "type": "string",
                        "description": "参考面板文件名"
                    },
                    "nthreads": {
                        "type": "integer",
                        "default": 50,
                        "description": "线程数"
                    },
                    "window": {
                        "type": "integer",
                        "default": 10,
                        "description": "填充窗口大小（cM）"
                    },
                    "overlap": {
                        "type": "integer",
                        "default": 2,
                        "description": "窗口重叠大小（cM）"
                    }
                },
                "required": ["workspace_id", "ref_panel"]
            }
        },
        {
            "name": "get_workspace_status",
            "description": """获取工作区的完整状态信息。
返回工作区的文件列表、校验结果、转换结果、填充结果等完整信息，用于向用户展示当前进度。""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "workspace_id": {
                        "type": "string",
                        "description": "工作区ID"
                    }
                },
                "required": ["workspace_id"]
            }
        },
        {
            "name": "list_workspaces",
            "description": "列出所有基因型填充工作区。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "返回的最大数量"
                    }
                }
            }
        },
        {
            "name": "delete_workspace",
            "description": "删除基因型填充工作区及其所有文件。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "workspace_id": {
                        "type": "string",
                        "description": "工作区ID"
                    }
                },
                "required": ["workspace_id"]
            }
        },
        {
            "name": "trigger_file_upload_dialog",
            "description": """触发前端文件上传对话框。
当用户确认要上传文件时，调用此工具向前端发送消息，弹出标准化的文件上传对话框。
需要在前端页面嵌入dify-interactive.html时使用。""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "workspace_id": {
                        "type": "string",
                        "description": "工作区ID"
                    }
                },
                "required": ["workspace_id"]
            }
        },
        {
            "name": "request_file_upload",
            "description": """【关键工具】请求文件上传并触发前端工作区显示。
在 create_imputation_workspace 创建成功后，必须调用此工具来：
1. 存储上传请求供前端轮询获取
2. 触发前端侧边栏工作区显示
3. 通知用户上传文件
这是连接后端工作区和前端界面的关键桥梁。""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "workspace_id": {
                        "type": "string",
                        "description": "工作区ID，由 create_imputation_workspace 返回"
                    },
                    "file_type": {
                        "type": "string",
                        "description": "期望的文件类型：vcf 或 plink，默认vcf"
                    },
                    "description": {
                        "type": "string",
                        "description": "上传说明信息，展示给用户"
                    }
                },
                "required": ["workspace_id", "file_type"]
            }
        }
    ]


# ==================== 工具执行实现 ====================

def _execute_tool_impl(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """执行工具的核心实现"""
    
    # ===== 原有工具 =====
    if name == "get_database_info":
        return tool.get_database_info(
            info_type=arguments.get('info_type', 'overview'),
            database_name=arguments.get('database_name')
        )
    if name == "query_breed_profile":
        return tool.query_breed_profile(
            breed_names=arguments.get('breed_names') or arguments.get('breeds'),
            exact_match=arguments.get('exact_match', False),
            max_results=arguments.get('max_results', 20),
            include_trait_values=arguments.get('include_trait_values', True),
        )
    if name == "query_sv":
        return tool.query_sv(
            query_type=arguments.get('query_type', 'region'),
            genes=arguments.get('genes'),
            window=arguments.get('window', 0),
            upstream=arguments.get('upstream'),
            downstream=arguments.get('downstream'),
            regions=arguments.get('regions'),
            chromosome=arguments.get('chromosome'),
            start_pos=arguments.get('start_pos'),
            end_pos=arguments.get('end_pos'),
            sv_ids=arguments.get('sv_ids'),
            filters=arguments.get('filters'),
            sv_type=arguments.get('sv_type'),
            breeds=arguments.get('breeds'),
            include_all_breeds=arguments.get('include_all_breeds', False),
            database_name=arguments.get('database_name'),
            search_all_databases=arguments.get('search_all_databases', False),
            include_annotation=arguments.get('include_annotation', True),
            max_results=arguments.get('max_results', 100)
        )
    if name == "query_annotation":
        return tool.query_annotation_v2(
            query_type=arguments.get('query_type', 'search'),
            queries=arguments.get('queries'),
            exact_match=arguments.get('exact_match', False),
            regions=arguments.get('regions'),
            chromosome=arguments.get('chromosome'),
            start_pos=arguments.get('start_pos'),
            end_pos=arguments.get('end_pos'),
            positions=arguments.get('positions'),
            max_results=arguments.get('max_results', 50)
        )
    if name == "analyze_breed_association":
        return tool.analyze_breed_association(
            analysis_type=arguments.get('analysis_type', 'phenotype_overview'),
            phenotype_name=arguments.get('phenotype_name'),
            genes=arguments.get('genes'),
            window=arguments.get('window', 0),
            upstream=arguments.get('upstream'),
            downstream=arguments.get('downstream'),
            regions=arguments.get('regions'),
            chromosome=arguments.get('chromosome'),
            start_pos=arguments.get('start_pos'),
            end_pos=arguments.get('end_pos'),
            sv_ids=arguments.get('sv_ids'),
            sv_type=arguments.get('sv_type'),
            database_name=arguments.get('database_name'),
            search_all_databases=arguments.get('search_all_databases', False),
            include_annotation=arguments.get('include_annotation', True),
            method=arguments.get('method', 'auto'),
            aggregate_method=arguments.get('aggregate_method', 'mean'),
            covariate_mode=arguments.get('covariate_mode', 'none'),
            categorical_covariates=arguments.get('categorical_covariates'),
            numeric_covariates=arguments.get('numeric_covariates'),
            stratify_by=arguments.get('stratify_by'),
            min_breeds=arguments.get('min_breeds', 8),
            min_stratum_breeds=arguments.get('min_stratum_breeds', 4),
            max_variants=arguments.get('max_variants', 100),
            top_n=arguments.get('top_n', 20),
            permutations=arguments.get('permutations', 200),
            random_seed=arguments.get('random_seed', 42)
        )
    if name == "run_analysis_task":
        return tool.run_analysis_task(
            task_name=arguments.get('task_name', 'analysis_task'),
            description=arguments.get('description'),
            steps=arguments.get('steps'),
            stop_on_error=arguments.get('stop_on_error', True),
        )
    if name == "genome_wide_association_scan":
        return tool.genome_wide_association_scan(
            phenotype_name=arguments.get('phenotype_name'),
            method=arguments.get('method', 'auto'),
            covariate_mode=arguments.get('covariate_mode', 'none'),
            categorical_covariates=arguments.get('categorical_covariates'),
            numeric_covariates=arguments.get('numeric_covariates'),
            stratify_by=arguments.get('stratify_by'),
            min_breeds=arguments.get('min_breeds', 8),
            min_stratum_breeds=arguments.get('min_stratum_breeds', 4),
            database_name=arguments.get('database_name'),
            search_all_databases=arguments.get('search_all_databases', False),
            sv_type=arguments.get('sv_type'),
            chromosomes=arguments.get('chromosomes'),
            include_annotation=arguments.get('include_annotation', True),
            top_n=arguments.get('top_n', 20),
            rank_by=arguments.get('rank_by', 'p_value'),
            sort_order=arguments.get('sort_order', 'asc'),
            min_abs_correlation=arguments.get('min_abs_correlation'),
        )
    
    # ===== 新增工具执行：AI引导式数据填充工作流 =====
    if name == "create_imputation_workspace":
        result = workspace_manager.create_workspace(
            output_path=arguments.get('output_path'),
            description=arguments.get('description')
        )
        try:
            import requests
            backend_resp = requests.post(f'{BACKEND_URL.rstrip("/")}/api/v1/workspaces', json={
                'workspace_type': arguments.get('workspace_type', 'imputation'),
                'description': arguments.get('description', ''),
                'workspace_id': result['workspace_id'],
            }, timeout=5)
            if backend_resp.status_code == 200:
                backend_data = backend_resp.json()
                result['backend_registered'] = True
                result['workspace_id'] = backend_data.get('workspace_id', result['workspace_id'])
        except Exception as e:
            logger.warning(f"注册工作区到后端失败: {e}")
            result['backend_registered'] = False
        return result
    
    if name == "validate_workspace_files":
        return workspace_manager.validate_input_files(arguments.get('workspace_id'))
    
    if name == "convert_workspace_files":
        return workspace_manager.convert_plink_to_vcf(
            workspace_id=arguments.get('workspace_id'),
            output_name=arguments.get('output_name')
        )
    
    if name == "run_workspace_imputation":
        workspace_id = arguments.get('workspace_id')
        ref_panel = arguments.get('ref_panel')
        
        # 获取输入文件
        input_info = workspace_manager.get_input_for_imputation(workspace_id)
        if not input_info.get('success'):
            return {'success': False, 'error': input_info.get('error', '无法获取输入文件')}
        
        # 执行填充
        result = imputation_tool.run_imputation(
            input_vcf=input_info['path'],
            ref_panel=ref_panel,
            output_name=f"imputed_{workspace_id}",
            nthreads=arguments.get('nthreads', 50),
            window=arguments.get('window', 10),
            overlap=arguments.get('overlap', 2)
        )
        
        # 更新工作区结果
        workspace_manager.update_imputation_result(workspace_id, result)
        
        return result
    
    if name == "get_workspace_status":
        workspace = workspace_manager.get_workspace(arguments.get('workspace_id'))
        if not workspace:
            return {'success': False, 'error': '工作区不存在'}
        return {'success': True, 'workspace': workspace}
    
    if name == "list_workspaces":
        return {
            'success': True,
            'workspaces': workspace_manager.list_workspaces(limit=arguments.get('limit', 20)),
            'total': len(workspace_manager._workspaces)
        }
    
    if name == "delete_workspace":
        success = workspace_manager.delete_workspace(arguments.get('workspace_id'))
        return {'success': success, 'message': '工作区已删除' if success else '删除失败'}
    
    if name == "trigger_file_upload_dialog":
        # 返回触发上传对话框的指令
        workspace_id = arguments.get('workspace_id')
        session_id = arguments.get('session_id')  # 可选的会话ID，用于关联前端
        
        # 存储上传请求，供前端轮询获取
        request_id = store_upload_request(workspace_id, session_id)
        
        return {
            'success': True,
            'action': 'TRIGGER_UPLOAD_DIALOG',
            'workspace_id': workspace_id,
            'request_id': request_id,
            'instructions': {
                'frontend_integration': '请在前端调用 openImputationUpload() 函数',
                'message_post': {
                    'type': 'OPEN_IMPUTATION_UPLOAD',
                    'workspace_id': workspace_id
                },
                'polling_api': f'/mcp/v1/imputation/pending-uploads?session_id={session_id or ""}'
            },
            'next_steps': [
                '前端弹出文件上传对话框',
                '用户选择并上传文件',
                '文件保存到工作区的input目录',
                '调用 validate_workspace_files 进行校验'
            ]
        }
    
    if name == "request_file_upload":
        # 【关键工具】请求文件上传并触发前端工作区显示
        workspace_id = arguments.get('workspace_id')
        file_type = arguments.get('file_type') or arguments.get('file_types', 'vcf')
        if isinstance(file_type, list):
            file_type = ','.join(file_type)
        description = arguments.get('description', '请上传需要填充的基因型数据文件')
        session_id = arguments.get('session_id')
        
        # 验证工作区是否存在
        ws_info = workspace_manager.get_workspace(workspace_id)
        if not ws_info:
            return {
                'success': False,
                'error': f'工作区不存在: {workspace_id}',
                'workspace_id': workspace_id
            }
        
        # 存储上传请求，供前端轮询获取
        request_id = store_upload_request(workspace_id, session_id)
        
        logger.info(f"[request_file_upload] 创建上传请求: workspace={workspace_id}, request={request_id}")
        
        return {
            'success': True,
            'action': 'TRIGGER_UPLOAD_DIALOG',
            'workspace_id': workspace_id,
            'request_id': request_id,
            'file_type': file_type,
            'description': description,
            'message': '已触发前端工作区显示，用户可以在侧边栏中上传文件',
            'instructions': {
                'frontend_integration': '前端将通过轮询获取此上传请求并自动展开工作区',
                'polling_api': f'/mcp/v1/imputation/pending-uploads?session_id={session_id or ""}',
                'expected_frontend_behavior': [
                    '检测到待处理的上传请求',
                    '自动展开侧边栏工作区',
                    '显示文件上传界面',
                    '用户完成上传后，文件自动保存到工作区'
                ]
            },
            'next_steps': [
                '等待用户在前端上传文件',
                '文件自动保存到工作区的input目录',
                '调用 validate_workspace_files 进行校验',
                '校验通过后执行填充'
            ]
        }
    
    raise ValueError(f"未知工具: {name}")


def _with_governance_meta(result: Dict[str, Any], tool_name: str, arguments: Dict[str, Any], trace_id: str, task_id: str = '') -> Dict[str, Any]:
    enriched = result if isinstance(result, dict) else {'raw_result': result}
    args_digest = hashlib.sha256(json.dumps(arguments or {}, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()[:16]
    enriched['_governance'] = {
        'trace_id': trace_id,
        'task_id': task_id or None,
        'tool_name': tool_name,
        'server_version': SERVER_INFO['version'],
        'data_version': DATA_VERSION,
        'parameter_digest': args_digest,
        'parameter_snapshot': arguments or {},
        'generated_at': _utc_now_iso(),
    }
    return enriched


def _execute_tool_for_task(name: str, arguments: Dict[str, Any], trace_id: str, task_id: str) -> Dict[str, Any]:
    result = _execute_tool_impl(name, arguments)
    return _with_governance_meta(result, name, arguments, trace_id=trace_id, task_id=task_id)


async def call_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """调用工具"""
    logger.info(f"调用工具: {name}")
    
    try:
        trace_id = str(uuid.uuid4())
        result = _execute_tool_impl(name, arguments)
        result = _with_governance_meta(result, name, arguments, trace_id=trace_id)
        
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}], "isError": False}
    except Exception as e:
        logger.error(f"工具调用失败: {e}")
        return {"content": [{"type": "text", "text": json.dumps({"error": str(e)})}], "isError": True}


# ==================== MCP HTTP 端点 ====================

@app.route('/mcp/v1/initialize', methods=['POST'])
def initialize():
    request_data = request.get_json() or {}
    return jsonify({
        "jsonrpc": "2.0",
        "id": request_data.get("id", 1),
        "result": {
            "protocolVersion": SERVER_INFO["protocolVersion"],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_INFO["name"], "version": SERVER_INFO["version"]}
        }
    })


@app.route('/mcp/v1/tools/list', methods=['POST', 'GET'])
def list_tools():
    request_data = request.get_json() if request.method == 'POST' else {}
    return jsonify({
        "jsonrpc": "2.0",
        "id": request_data.get("id", 1),
        "result": {"tools": get_tool_schema()}
    })


@app.route('/mcp/v1/tools/call', methods=['POST'])
@async_to_sync
async def call_tool_endpoint():
    request_data = request.get_json(silent=True) or {}
    params = request_data.get("params") or {}
    tool_name = params.get("name") or request_data.get("name")
    arguments = params.get("arguments") or request_data.get("arguments") or {}
    
    # 获取会话ID（从请求头或参数中）
    session_id = request.headers.get('X-Session-ID') or request_data.get('session_id') or 'default'
    
    if not tool_name:
        return jsonify({"jsonrpc": "2.0", "id": request_data.get("id", 1), "error": {"code": -32602, "message": "缺少工具名称"}}), 400
    
    # ===== 工具调用治理检查（防止循环调用）=====
    allowed, reason, meta = tool_governor.check_and_record(session_id, tool_name, arguments)
    
    if not allowed:
        logger.warning(f"[ToolGovernor] 阻止工具调用: {tool_name}, 原因: {reason}, 会话: {session_id}")
        return jsonify({
            "jsonrpc": "2.0",
            "id": request_data.get("id", 1),
            "error": {
                "code": -32000,
                "message": reason,
                "data": {
                    "type": "tool_call_prevented",
                    "tool": tool_name,
                    "reason": meta.get('reason'),
                    "suggestion": "请等待当前操作完成或明确您的需求后重试"
                }
            }
        }), 429
    
    logger.info(f"[ToolGovernor] 允许工具调用: {tool_name}, 会话: {session_id}, 元数据: {meta}")
    
    # 执行工具调用
    result = await call_tool(tool_name, arguments)
    
    # 记录调用结果
    tool_governor.record_result(session_id, tool_name, result)
    
    # 添加治理元数据到结果
    if isinstance(result, dict):
        result['_governance_meta'] = {
            'call_number': meta.get('call_number'),
            'total_calls': meta.get('total_calls'),
            'session_id': session_id
        }
    
    return jsonify({"jsonrpc": "2.0", "id": request_data.get("id", 1), "result": result})


@app.route('/mcp/v1', methods=['GET', 'POST'])
def mcp_discovery():
    if request.method == 'POST':
        request_data = request.get_json(silent=True) or {}
        method = request_data.get("method")
        if "id" not in request_data:
            return ("", 204)
        if method == "initialize":
            return initialize()
        if method == "tools/list":
            return list_tools()
        if method == "tools/call":
            return call_tool_endpoint()
        return jsonify({"jsonrpc": "2.0", "id": request_data.get("id", 1), "result": {"tools": get_tool_schema()}})
    
    return jsonify({
        "name": SERVER_INFO["name"],
        "version": SERVER_INFO["version"],
        "description": SERVER_INFO["description"],
        "tools_available": len(get_tool_schema())
    })


@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "tools_available": len(get_tool_schema()),
        "server_version": SERVER_INFO['version'],
        "data_version": DATA_VERSION,
    })


# ==================== 任务管理端点 ====================

@app.route('/mcp/v1/tasks/submit', methods=['POST'])
def submit_task():
    payload = request.get_json(silent=True) or {}
    tool_name = payload.get('name') or payload.get('tool_name')
    arguments = payload.get('arguments') or {}
    max_retries = int(payload.get('max_retries', 1))
    if not tool_name:
        return jsonify({'success': False, 'error': '缺少 name/tool_name'}), 400
    task = TASK_MANAGER.submit(
        tool_name=tool_name,
        arguments=arguments,
        execute_fn=_execute_tool_for_task,
        data_version=DATA_VERSION,
        max_retries=max_retries,
    )
    return jsonify(task)


@app.route('/mcp/v1/tasks/<task_id>', methods=['GET'])
def get_task(task_id: str):
    include_result = request.args.get('include_result', 'true').lower() != 'false'
    snap = TASK_MANAGER.get_snapshot(task_id, include_result=include_result)
    code = 200 if snap.get('success') else 404
    return jsonify(snap), code


@app.route('/mcp/v1/tasks', methods=['GET'])
def list_tasks_endpoint():
    limit = int(request.args.get('limit', 100))
    return jsonify(TASK_MANAGER.list_tasks(limit=limit))


@app.route('/mcp/v1/tasks/<task_id>/cancel', methods=['POST'])
def cancel_task(task_id: str):
    result = TASK_MANAGER.cancel(task_id)
    code = 200 if result.get('success') else 400
    return jsonify(result), code


@app.route('/mcp/v1/tasks/<task_id>/retry', methods=['POST'])
def retry_task(task_id: str):
    result = TASK_MANAGER.retry(task_id, execute_fn=_execute_tool_for_task)
    code = 200 if result.get('success') else 400
    return jsonify(result), code


# ==================== 文件上传端点 ====================

@app.route('/upload', methods=['POST'])
def upload_file():
    """
    文件上传端点
    
    支持 multipart/form-data 格式上传 VCF 文件
    返回：上传文件的本地路径和验证信息
    """
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '请求中未找到文件字段（应为 "file"）'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': '未选择文件'}), 400
    
    # 生成任务ID
    task_id = str(uuid.uuid4())[:8]
    
    try:
        # 读取文件内容
        file_content = file.read()
        
        # 保存文件
        saved_path = imputation_tool.save_uploaded_file(
            file_content=file_content,
            original_filename=file.filename,
            task_id=task_id
        )
        
        # 验证VCF
        validation = imputation_tool.validate_vcf(saved_path)
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'original_filename': file.filename,
            'saved_path': saved_path,
            'file_size_mb': round(len(file_content) / (1024 * 1024), 2),
            'validation': validation
        })
        
    except Exception as e:
        logger.error(f"文件上传失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/download/<path:filename>', methods=['GET'])
def download_file(filename):
    """
    文件下载端点
    
    支持下载填充结果文件
    """
    # 安全检查：防止目录遍历
    if '..' in filename or filename.startswith('/'):
        return jsonify({'success': False, 'error': '非法文件名'}), 400
    
    # 在输出目录中查找文件
    file_path = os.path.join(imputation_tool.output_dir, filename)
    
    if not os.path.exists(file_path):
        # 也尝试在上传目录中查找
        file_path = os.path.join(imputation_tool.uploads_dir, filename)
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'error': '文件不存在'}), 404
    
    try:
        return send_file(
            file_path,
            as_attachment=True,
            download_name=os.path.basename(file_path)
        )
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/files', methods=['GET'])
def list_files():
    """列出上传和输出的文件"""
    file_type = request.args.get('type', 'all')  # 'uploads', 'outputs', 'all'
    
    result = {'uploads': [], 'outputs': []}
    
    if file_type in ['uploads', 'all']:
        if os.path.isdir(imputation_tool.uploads_dir):
            for f in os.listdir(imputation_tool.uploads_dir):
                path = os.path.join(imputation_tool.uploads_dir, f)
                if os.path.isfile(path):
                    stat = os.stat(path)
                    result['uploads'].append({
                        'filename': f,
                        'size_mb': round(stat.st_size / (1024 * 1024), 2),
                        'modified_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
                    })
    
    if file_type in ['outputs', 'all']:
        if os.path.isdir(imputation_tool.output_dir):
            for f in os.listdir(imputation_tool.output_dir):
                path = os.path.join(imputation_tool.output_dir, f)
                if os.path.isfile(path):
                    stat = os.stat(path)
                    result['outputs'].append({
                        'filename': f,
                        'size_mb': round(stat.st_size / (1024 * 1024), 2),
                        'modified_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
                    })
    
    return jsonify({'success': True, 'files': result})


# ==================== 工作区管理端点 ====================

@app.route('/mcp/v1/imputation/workspaces', methods=['POST'])
def create_workspace_endpoint():
    """创建工作区端点"""
    payload = request.get_json(silent=True) or {}
    result = workspace_manager.create_workspace(
        output_path=payload.get('output_path'),
        description=payload.get('description')
    )
    return jsonify(result)


@app.route('/mcp/v1/imputation/workspaces', methods=['GET'])
def list_workspaces_endpoint():
    """列出工作区端点"""
    limit = int(request.args.get('limit', 20))
    workspaces = workspace_manager.list_workspaces(limit=limit)
    return jsonify({'success': True, 'workspaces': workspaces, 'total': len(workspace_manager._workspaces)})


@app.route('/mcp/v1/imputation/workspaces/<workspace_id>', methods=['GET'])
def get_workspace_endpoint(workspace_id: str):
    """获取工作区详情端点"""
    workspace = workspace_manager.get_workspace(workspace_id)
    if not workspace:
        return jsonify({'success': False, 'error': '工作区不存在'}), 404
    return jsonify({'success': True, 'workspace': workspace})


@app.route('/mcp/v1/imputation/workspaces/<workspace_id>', methods=['DELETE'])
def delete_workspace_endpoint(workspace_id: str):
    """删除工作区端点"""
    success = workspace_manager.delete_workspace(workspace_id)
    if success:
        return jsonify({'success': True, 'message': '工作区已删除'})
    return jsonify({'success': False, 'error': '删除失败或工作区不存在'}), 400


@app.route('/mcp/v1/imputation/workspaces/<workspace_id>/validate', methods=['POST'])
def validate_workspace_endpoint(workspace_id: str):
    """校验工作区文件端点"""
    result = workspace_manager.validate_input_files(workspace_id)
    return jsonify(result)


@app.route('/mcp/v1/imputation/workspaces/<workspace_id>/convert', methods=['POST'])
def convert_workspace_endpoint(workspace_id: str):
    """转换工作区文件端点"""
    payload = request.get_json(silent=True) or {}
    result = workspace_manager.convert_plink_to_vcf(
        workspace_id=workspace_id,
        output_name=payload.get('output_name')
    )
    return jsonify(result)


@app.route('/mcp/v1/imputation/sync-upload', methods=['POST'])
def sync_upload_endpoint():
    """
    后端上传文件后通知MCP同步
    M CP会扫描真实文件系统更新workspace的index

    请求体:
    {
        "workspace_id": "ws_20260415_013548",
        "filename": "test.vcf.gz",
        "file_size": 123456
    }
    """
    payload = request.get_json()
    if not payload:
        return jsonify({'success': False, 'error': '请求体不能为空'}), 400

    workspace_id = payload.get('workspace_id')
    filename = payload.get('filename')
    file_size = payload.get('file_size', 0)

    if not workspace_id or not filename:
        return jsonify({'success': False, 'error': '缺少必要参数'}), 400

    workspace = workspace_manager.get_workspace(workspace_id)
    if not workspace:
        return jsonify({'success': False, 'error': '工作区不存在'}), 404

    file_path = os.path.join(workspace['directories']['input'], filename)
    if not os.path.exists(file_path):
        return jsonify({'success': False, 'error': f'文件不存在: {file_path}'}), 404

    import hashlib
    with open(file_path, 'rb') as f:
        content = f.read()
    md5_hash = hashlib.md5(content).hexdigest()

    file_info = {
        'filename': filename,
        'path': file_path,
        'size_bytes': len(content),
        'size_mb': round(len(content) / (1024 * 1024), 2),
        'uploaded_at': datetime.now(timezone.utc).isoformat(),
        'md5': md5_hash
    }

    workspace['files']['input'].append(file_info)
    workspace_manager._save_index()

    logger.info(f"MCP同步文件记录: {workspace_id}/{filename}")
    return jsonify({'success': True, 'file_info': file_info})


@app.route('/mcp/v1/imputation/pending-uploads', methods=['GET'])
def get_pending_uploads_endpoint():
    """
    获取待处理的上传请求列表（供前端轮询）
    
    查询参数:
    - session_id: 可选，用于筛选特定会话的请求
    """
    session_id = request.args.get('session_id')
    pending = get_pending_upload_requests(session_id)
    return jsonify({
        'success': True,
        'pending_requests': pending,
        'count': len(pending)
    })


@app.route('/mcp/v1/imputation/upload', methods=['POST'])
def upload_to_workspace_endpoint():
    """
    上传文件到工作区端点
    
    支持 multipart/form-data 格式上传多个文件
    """
    workspace_id = request.form.get('workspace_id')
    if not workspace_id:
        return jsonify({'success': False, 'error': '缺少workspace_id参数'}), 400
    
    workspace = workspace_manager.get_workspace(workspace_id)
    if not workspace:
        return jsonify({'success': False, 'error': '工作区不存在'}), 404
    
    if 'files' not in request.files:
        return jsonify({'success': False, 'error': '请求中未找到文件字段（应为 "files"）'}), 400
    
    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'success': False, 'error': '未选择文件'}), 400
    
    uploaded_files = []
    errors = []
    
    for file in files:
        if file.filename == '':
            continue
        
        try:
            file_content = file.read()
            result = workspace_manager.save_uploaded_file(
                workspace_id=workspace_id,
                file_content=file_content,
                filename=file.filename
            )
            
            if result.get('success'):
                uploaded_files.append(result['file_info'])
            else:
                errors.append({'filename': file.filename, 'error': result.get('error')})
                
        except Exception as e:
            logger.error(f"文件上传失败 {file.filename}: {e}")
            errors.append({'filename': file.filename, 'error': str(e)})
    
    return jsonify({
        'success': len(uploaded_files) > 0,
        'workspace_id': workspace_id,
        'files_count': len(uploaded_files),
        'uploaded_files': uploaded_files,
        'errors': errors if errors else None
    })


# ==================== 新增：对话管理和治理API ====================

@app.route('/api/v1/sessions/<session_id>/reset', methods=['POST'])
def reset_session_endpoint(session_id: str):
    """
    重置会话状态
    当用户开始新话题时调用，清除工具调用计数和对话状态
    """
    try:
        # 重置工具治理器中的会话
        tool_governor.reset_turn(session_id)
        
        # 重置对话管理器中的会话
        session = conversation_manager.get_or_create_session(session_id)
        session.increment_turn()
        
        logger.info(f"[Session] 重置会话: {session_id}")
        
        return jsonify({
            'success': True,
            'message': '会话已重置',
            'session_id': session_id,
            'new_turn': session.turn_count
        })
    except Exception as e:
        logger.error(f"重置会话失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/v1/sessions/<session_id>/stats', methods=['GET'])
def get_session_stats_endpoint(session_id: str):
    """
    获取会话统计信息
    用于监控工具调用情况和对话状态
    """
    try:
        # 获取工具治理统计
        governor_stats = tool_governor.get_session_stats(session_id)
        
        # 获取对话会话
        session = conversation_manager.get_session(session_id)
        
        if session:
            conversation_stats = session.to_dict()
        else:
            conversation_stats = {'session_id': session_id, 'exists': False}
        
        return jsonify({
            'success': True,
            'tool_governance': governor_stats,
            'conversation': conversation_stats
        })
    except Exception as e:
        logger.error(f"获取会话统计失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/v1/sessions/<session_id>/intent', methods=['POST'])
def detect_intent_endpoint(session_id: str):
    """
    检测用户意图
    用于前端理解用户需求，决定后续流程
    """
    try:
        data = request.get_json() or {}
        message = data.get('message', '')
        
        # 获取或创建会话
        session = conversation_manager.get_or_create_session(session_id)
        
        # 检测意图
        intent = conversation_manager.detect_intent(message, session.context)
        
        # 检查是否需要转换阶段
        new_phase = conversation_manager.should_transition_phase(session, intent)
        if new_phase:
            session.update_phase(new_phase)
        
        # 添加消息到会话
        from conversation_manager import Message
        msg = Message(role="user", content=message, intent=intent)
        session.add_message(msg)
        
        return jsonify({
            'success': True,
            'intent': {
                'type': intent.type.value,
                'confidence': intent.confidence,
                'entities': intent.entities
            },
            'current_phase': session.phase.value,
            'suggested_action': self._get_suggested_action(intent, session)
        })
    except Exception as e:
        logger.error(f"意图检测失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def _get_suggested_action(intent, session):
    """根据意图和会话状态建议下一步操作"""
    if intent.type.value == 'imputation':
        if not session.context.current_workspace_id:
            return 'create_workspace'
        else:
            return 'request_upload'
    elif intent.type.value == 'query':
        return 'execute_query'
    elif intent.type.value == 'analysis':
        return 'execute_analysis'
    else:
        return 'clarify'


@app.route('/api/v1/governance/stats', methods=['GET'])
def get_governance_stats_endpoint():
    """
    获取全局治理统计
    用于监控整体系统状态
    """
    try:
        stats = tool_governor.get_all_stats()
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        logger.error(f"获取治理统计失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/v1/imputation/workflow/init', methods=['POST'])
def init_imputation_workflow_endpoint():
    """
    初始化数据填充工作流
    一键创建工作区并准备上传流程
    """
    try:
        data = request.get_json() or {}
        session_id = data.get('session_id', 'default')
        description = data.get('description', '数据填充工作流')
        file_type = data.get('file_type', 'vcf')
        
        # 1. 创建工作区
        workspace = workspace_manager.create_workspace(description=description)
        workspace_id = workspace['workspace_id']
        
        # 2. 存储上传请求
        request_id = store_upload_request(workspace_id, session_id)
        
        # 3. 更新会话上下文
        session = conversation_manager.get_or_create_session(session_id)
        session.context.set_workspace(workspace_id)
        session.update_phase(ConversationPhase.UPLOAD_WAITING)
        
        logger.info(f"[Imputation] 初始化工作流: {workspace_id}, 会话: {session_id}")
        
        return jsonify({
            'success': True,
            'workflow': {
                'workspace_id': workspace_id,
                'request_id': request_id,
                'file_type': file_type,
                'status': 'awaiting_upload'
            },
            'instructions': {
                'action': 'OPEN_UPLOAD_DIALOG',
                'workspace_id': workspace_id,
                'message': '已为您创建数据填充工作区，请上传需要填充的基因型数据文件'
            }
        })
    except Exception as e:
        logger.error(f"初始化工作流失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/v1/imputation/workflow/<workspace_id>/execute', methods=['POST'])
def execute_imputation_workflow_endpoint(workspace_id: str):
    """
    执行完整的数据填充流程
    验证 -> 转换(如需要) -> 填充
    """
    try:
        data = request.get_json() or {}
        ref_panel = data.get('ref_panel', '2063.10.14.imiss0.2.panel.plink_ph.AN_AC.reiid.vcf.gz')
        nthreads = data.get('nthreads', 50)
        window = data.get('window', 10)
        overlap = data.get('overlap', 2)
        
        # 1. 验证文件
        validation_result = workspace_manager.validate_input_files(workspace_id)
        if not validation_result.get('success'):
            return jsonify({
                'success': False,
                'stage': 'validation',
                'error': validation_result.get('error', '文件验证失败')
            }), 400
        
        # 2. 如果需要，转换格式
        file_format = validation_result.get('format', '').lower()
        if file_format == 'plink':
            convert_result = workspace_manager.convert_plink_to_vcf(workspace_id)
            if not convert_result.get('success'):
                return jsonify({
                    'success': False,
                    'stage': 'conversion',
                    'error': convert_result.get('error', '格式转换失败')
                }), 400
        
        # 3. 执行填充
        imputation_result = imputation_tool.impute_workspace(
            workspace_id=workspace_id,
            ref_panel=ref_panel,
            nthreads=nthreads,
            window=window,
            overlap=overlap
        )
        
        return jsonify({
            'success': True,
            'stage': 'completed',
            'workspace_id': workspace_id,
            'validation': validation_result,
            'imputation': imputation_result
        })
    except Exception as e:
        logger.error(f"执行工作流失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ==================== 主页（更新） ====================

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "name": SERVER_INFO["name"],
        "version": SERVER_INFO["version"],
        "description": SERVER_INFO["description"],
        "data_version": DATA_VERSION,
        "tools": [t["name"] for t in get_tool_schema()],
        "features": {
            "tool_governance": "已启用（防止循环调用）",
            "conversation_management": "已启用（状态追踪）",
            "imputation_workflow": "已启用（完整填充流程）"
        },
        "endpoints": {
            "mcp": {
                "tools_list": "/mcp/v1/tools/list",
                "tools_call": "/mcp/v1/tools/call",
            },
            "sessions": {
                "reset": "/api/v1/sessions/<session_id>/reset (POST)",
                "stats": "/api/v1/sessions/<session_id>/stats (GET)",
                "intent": "/api/v1/sessions/<session_id>/intent (POST)"
            },
            "governance": {
                "stats": "/api/v1/governance/stats (GET)"
            },
            "tasks": {
                "submit": "/mcp/v1/tasks/submit",
                "list": "/mcp/v1/tasks",
                "get": "/mcp/v1/tasks/<task_id>",
                "cancel": "/mcp/v1/tasks/<task_id>/cancel",
                "retry": "/mcp/v1/tasks/<task_id>/retry"
            },
            "files": {
                "upload": "/upload (POST, multipart/form-data)",
                "download": "/download/<filename>",
                "list": "/files"
            },
            "imputation_workspaces": {
                "create": "/mcp/v1/imputation/workspaces (POST)",
                "list": "/mcp/v1/imputation/workspaces (GET)",
                "get": "/mcp/v1/imputation/workspaces/<workspace_id> (GET)",
                "delete": "/mcp/v1/imputation/workspaces/<workspace_id> (DELETE)",
                "validate": "/mcp/v1/imputation/workspaces/<workspace_id>/validate (POST)",
                "convert": "/mcp/v1/imputation/workspaces/<workspace_id>/convert (POST)",
                "upload_files": "/mcp/v1/imputation/upload (POST, multipart/form-data)",
                "workflow_init": "/api/v1/imputation/workflow/init (POST)",
                "workflow_execute": "/api/v1/imputation/workflow/<id>/execute (POST)"
            },
            "health": "/health"
        }
    })


if __name__ == '__main__':
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MCP_PORT
    
    logger.info(f"🚀 MCP HTTP 服务器启动中...")
    logger.info(f"📍 监听地址: http://localhost:{port}")
    logger.info(f"🔧 工具数量: {len(get_tool_schema())}")
    logger.info(f"🛡️  工具治理: 已启用（防止循环调用）")
    logger.info(f"💬 对话管理: 已启用（状态追踪）")
    logger.info(f"📦 参考面板目录: {imputation_tool.refpanel_dir}")
    logger.info(f"📤 上传目录: {imputation_tool.uploads_dir}")
    logger.info(f"📥 输出目录: {imputation_tool.output_dir}")
    logger.info(f"📁 工作区目录: {workspace_manager.base_dir}")
    
    app.run(host=MCP_HOST, port=port, debug=False, threaded=True)
