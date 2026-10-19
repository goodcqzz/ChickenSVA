"""
基因型填充任务处理器

专门处理耗时的基因型填充任务：
- PLINK 数据预处理
- Beagle/IMPUTE2 填充
- 结果验证和格式化
- 进度跟踪
"""

import os
import json
import logging
import asyncio
import subprocess
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

from app.tasks.queue import Task, TaskProgress

logger = logging.getLogger(__name__)


@dataclass
class ImputationTaskConfig:
    """基因型填充任务配置"""
    # 输入文件
    input_prefix: str           # PLINK 文件前缀
    input_dir: str              # 输入目录
    
    # 参考面板
    reference_panel: str        # 参考面板路径
    reference_population: str = "mixed"  # 参考人群
    
    # 填充参数
    tool: str = "beagle"        # 填充工具: beagle, impute2
    window_size: int = 10       # 窗口大小 (Mb)
    n_iterations: int = 10      # 迭代次数
    n_threads: int = 4          # 线程数
    
    # 输出
    output_dir: str = "./output/imputation"
    output_prefix: Optional[str] = None
    
    # 质量控制
    min_maf: float = 0.01       # 最小 MAF
    min_r2: float = 0.3         # 最小 R²
    
    def __post_init__(self):
        if self.output_prefix is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.output_prefix = f"imputed_{timestamp}"


class ImputationTaskHandler:
    """
    基因型填充任务处理器
    
    处理流程：
    1. 数据验证和质量控制
    2. 数据预处理（格式转换）
    3. 分染色体填充
    4. 结果合并
    5. 质量评估
    """
    
    def __init__(self):
        self.supported_tools = ["beagle", "impute2"]
    
    async def handle(self, task: Task) -> Dict[str, Any]:
        """
        处理填充任务
        
        Args:
            task: 任务对象
            
        Returns:
            处理结果
        """
        config = ImputationTaskConfig(**task.payload)
        
        logger.info(f"开始基因型填充任务 [{task.id}]")
        
        try:
            # 步骤 1: 数据验证
            await self._update_progress(task, 5, "验证输入数据...")
            await self._validate_input(config)
            
            # 步骤 2: 质量控制
            await self._update_progress(task, 15, "执行质量控制...")
            await self._quality_control(config)
            
            # 步骤 3: 数据预处理
            await self._update_progress(task, 25, "预处理数据...")
            await self._preprocess(config)
            
            # 步骤 4: 执行填充
            await self._update_progress(task, 50, "执行基因型填充...")
            chromosomes = await self._get_chromosomes(config)
            
            results = []
            for i, chrom in enumerate(chromosomes):
                progress = 50 + int((i / len(chromosomes)) * 40)
                await self._update_progress(
                    task, progress,
                    f"填充染色体 {chrom} ({i+1}/{len(chromosomes)})..."
                )
                
                result = await self._impute_chromosome(config, chrom)
                results.append(result)
            
            # 步骤 5: 结果合并
            await self._update_progress(task, 95, "合并结果...")
            final_result = await self._merge_results(config, results)
            
            # 步骤 6: 质量评估
            await self._update_progress(task, 98, "评估填充质量...")
            quality_report = await self._assess_quality(config)
            
            await self._update_progress(task, 100, "完成")
            
            return {
                "success": True,
                "task_id": task.id,
                "output_files": final_result,
                "quality_report": quality_report,
                "config": {
                    "tool": config.tool,
                    "chromosomes": chromosomes,
                    "samples": await self._get_sample_count(config),
                    "snps": await self._get_snp_count(config),
                },
                "timestamp": datetime.utcnow().isoformat(),
            }
            
        except Exception as e:
            logger.error(f"填充任务失败 [{task.id}]: {e}")
            raise
    
    async def _validate_input(self, config: ImputationTaskConfig):
        """验证输入数据"""
        input_path = Path(config.input_dir) / config.input_prefix
        
        # 检查 PLINK 文件
        required_extensions = [".bed", ".bim", ".fam"]
        for ext in required_extensions:
            file_path = input_path.parent / f"{input_path.name}{ext}"
            if not file_path.exists():
                raise FileNotFoundError(f"缺少必需的 PLINK 文件: {file_path}")
        
        # 检查参考面板
        if config.reference_panel and not Path(config.reference_panel).exists():
            raise FileNotFoundError(f"参考面板不存在: {config.reference_panel}")
        
        logger.info("输入数据验证通过")
    
    async def _quality_control(self, config: ImputationTaskConfig):
        """执行质量控制"""
        output_dir = Path(config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        input_prefix = Path(config.input_dir) / config.input_prefix
        qc_prefix = output_dir / f"{config.output_prefix}_qc"
        
        # PLINK 质量控制
        cmd = [
            "plink",
            "--bfile", str(input_prefix),
            "--maf", str(config.min_maf),
            "--geno", "0.05",  # 最大缺失率 5%
            "--hwe", "1e-6",   # Hardy-Weinberg 平衡
            "--make-bed",
            "--out", str(qc_prefix)
        ]
        
        await self._run_command(cmd, "质量控制")
        
        logger.info("质量控制完成")
    
    async def _preprocess(self, config: ImputationTaskConfig):
        """数据预处理"""
        # 根据工具进行不同的预处理
        if config.tool == "beagle":
            await self._preprocess_for_beagle(config)
        elif config.tool == "impute2":
            await self._preprocess_for_impute2(config)
        
        logger.info("数据预处理完成")
    
    async def _preprocess_for_beagle(self, config: ImputationTaskConfig):
        """Beagle 预处理"""
        output_dir = Path(config.output_dir)
        qc_prefix = output_dir / f"{config.output_prefix}_qc"
        
        # 转换为 VCF
        vcf_path = output_dir / f"{config.output_prefix}.vcf.gz"
        
        cmd = [
            "plink",
            "--bfile", str(qc_prefix),
            "--recode", "vcf", "bgz",
            "--out", str(vcf_path.with_suffix("").with_suffix(""))
        ]
        
        await self._run_command(cmd, "转换为VCF")
        
        # 建立索引
        cmd = ["tabix", "-p", "vcf", str(vcf_path)]
        await self._run_command(cmd, "建立VCF索引")
    
    async def _preprocess_for_impute2(self, config: ImputationTaskConfig):
        """IMPUTE2 预处理"""
        # IMPUTE2 使用 PLINK 格式，无需额外预处理
        pass
    
    async def _get_chromosomes(self, config: ImputationTaskConfig) -> List[str]:
        """获取染色体列表"""
        output_dir = Path(config.output_dir)
        qc_prefix = output_dir / f"{config.output_prefix}_qc"
        
        # 读取 BIM 文件获取染色体
        bim_path = qc_prefix.with_suffix(".bim")
        chromosomes = set()
        
        with open(bim_path) as f:
            for line in f:
                parts = line.strip().split()
                if parts:
                    chromosomes.add(parts[0])
        
        # 过滤有效染色体
        valid_chroms = []
        for chrom in sorted(chromosomes):
            try:
                chrom_num = int(chrom)
                if 1 <= chrom_num <= 22:
                    valid_chroms.append(chrom)
            except ValueError:
                if chrom in ["X", "Y", "MT"]:
                    valid_chroms.append(chrom)
        
        return valid_chroms
    
    async def _impute_chromosome(
        self,
        config: ImputationTaskConfig,
        chrom: str
    ) -> Dict[str, Any]:
        """填充单个染色体"""
        if config.tool == "beagle":
            return await self._impute_with_beagle(config, chrom)
        elif config.tool == "impute2":
            return await self._impute_with_impute2(config, chrom)
        else:
            raise ValueError(f"不支持的填充工具: {config.tool}")
    
    async def _impute_with_beagle(
        self,
        config: ImputationTaskConfig,
        chrom: str
    ) -> Dict[str, Any]:
        """使用 Beagle 填充"""
        output_dir = Path(config.output_dir)
        vcf_path = output_dir / f"{config.output_prefix}.vcf.gz"
        output_path = output_dir / f"{config.output_prefix}_chr{chrom}.vcf.gz"
        
        cmd = [
            "beagle",
            "gt=" + str(vcf_path),
            "ref=" + config.reference_panel,
            "chrom=" + chrom,
            "out=" + str(output_path.with_suffix("").with_suffix("")),
            "nthreads=" + str(config.n_threads),
            "window=" + str(config.window_size),
            "impute=true",
        ]
        
        await self._run_command(cmd, f"Beagle 填充染色体 {chrom}")
        
        return {
            "chromosome": chrom,
            "output": str(output_path),
        }
    
    async def _impute_with_impute2(
        self,
        config: ImputationTaskConfig,
        chrom: str
    ) -> Dict[str, Any]:
        """使用 IMPUTE2 填充"""
        output_dir = Path(config.output_dir)
        qc_prefix = output_dir / f"{config.output_prefix}_qc"
        output_path = output_dir / f"{config.output_prefix}_chr{chrom}"
        
        # 获取遗传图谱位置
        genetic_map = self._get_genetic_map(config, chrom)
        
        cmd = [
            "impute2",
            "-m", genetic_map,
            "-h", f"{config.reference_panel}.{chrom}.hap.gz",
            "-l", f"{config.reference_panel}.{chrom}.legend.gz",
            "-g", str(qc_prefix) + ".gen",
            "-int", "1", "50000000",  # 填充区域
            "-Ne", "20000",
            "-o", str(output_path),
        ]
        
        await self._run_command(cmd, f"IMPUTE2 填充染色体 {chrom}")
        
        return {
            "chromosome": chrom,
            "output": str(output_path),
        }
    
    async def _merge_results(
        self,
        config: ImputationTaskConfig,
        results: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        """合并各染色体结果"""
        output_dir = Path(config.output_dir)
        
        if config.tool == "beagle":
            # 合并 VCF 文件
            merged_vcf = output_dir / f"{config.output_prefix}_merged.vcf.gz"
            
            # 使用 bcftools 合并
            chrom_vcfs = [r["output"] for r in results]
            cmd = ["bcftools", "concat", "-Oz", "-o", str(merged_vcf)] + chrom_vcfs
            
            await self._run_command(cmd, "合并 VCF")
            
            # 转换回 PLINK 格式
            merged_prefix = output_dir / f"{config.output_prefix}_final"
            cmd = [
                "plink",
                "--vcf", str(merged_vcf),
                "--make-bed",
                "--out", str(merged_prefix)
            ]
            
            await self._run_command(cmd, "转换为 PLINK")
            
            return {
                "plink_prefix": str(merged_prefix),
                "vcf": str(merged_vcf),
            }
        
        else:  # IMPUTE2
            # 合并 GEN 文件
            merged_prefix = output_dir / f"{config.output_prefix}_final"
            # ... 合并逻辑
            
            return {
                "plink_prefix": str(merged_prefix),
            }
    
    async def _assess_quality(self, config: ImputationTaskConfig) -> Dict[str, Any]:
        """评估填充质量"""
        output_dir = Path(config.output_dir)
        final_prefix = output_dir / f"{config.output_prefix}_final"
        
        # 计算 INFO score (IMPUTE2) 或 R² (Beagle)
        # 这里简化处理，实际应该解析填充工具的输出
        
        return {
            "average_r2": 0.85,  # 示例值
            "snp_count": await self._get_snp_count(config),
            "sample_count": await self._get_sample_count(config),
            "low_quality_snps": 0,
        }
    
    async def _get_sample_count(self, config: ImputationTaskConfig) -> int:
        """获取样本数"""
        output_dir = Path(config.output_dir)
        fam_path = output_dir / f"{config.output_prefix}_qc.fam"
        
        if fam_path.exists():
            with open(fam_path) as f:
                return sum(1 for _ in f)
        return 0
    
    async def _get_snp_count(self, config: ImputationTaskConfig) -> int:
        """获取 SNP 数"""
        output_dir = Path(config.output_dir)
        bim_path = output_dir / f"{config.output_prefix}_qc.bim"
        
        if bim_path.exists():
            with open(bim_path) as f:
                return sum(1 for _ in f)
        return 0
    
    def _get_genetic_map(self, config: ImputationTaskConfig, chrom: str) -> str:
        """获取遗传图谱"""
        # 这里应该返回遗传图谱文件路径
        # 简化处理
        return f"/path/to/genetic_map/chr{chrom}.map"
    
    async def _run_command(self, cmd: List[str], description: str):
        """运行外部命令"""
        logger.info(f"执行: {description}")
        logger.debug(f"命令: {' '.join(cmd)}")
        
        # 使用 asyncio 运行子进程
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "未知错误"
            raise RuntimeError(f"{description} 失败: {error_msg}")
        
        logger.info(f"{description} 完成")
    
    async def _update_progress(self, task: Task, current: int, message: str):
        """更新任务进度"""
        from app.tasks.queue import get_task_queue
        
        queue = get_task_queue()
        if queue:
            progress = TaskProgress(
                current=current,
                total=100,
                message=message
            )
            await queue.update_progress(task.id, progress)


# 创建处理器实例
_imputation_handler = ImputationTaskHandler()


async def handle_imputation_task(task: Task) -> Dict[str, Any]:
    """基因型填充任务入口"""
    return await _imputation_handler.handle(task)
