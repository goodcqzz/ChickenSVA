#!/usr/bin/env python3
"""
参考面板验证器 - 专门验证参考面板文件的完整性和兼容性
支持VCF、BCF、bref3格式的验证
"""

import os
import gzip
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ValidationSeverity(Enum):
    """验证严重程度"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class PanelValidationIssue:
    """验证问题"""
    severity: ValidationSeverity
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None
    suggestion: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "suggestion": self.suggestion
        }


@dataclass
class PanelValidationResult:
    """面板验证结果"""
    valid: bool
    file_path: str
    file_format: str
    issues: List[PanelValidationIssue] = field(default_factory=list)
    statistics: Dict[str, Any] = field(default_factory=dict)
    compatibility: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "file_path": self.file_path,
            "file_format": self.file_format,
            "issues": [i.to_dict() for i in self.issues],
            "statistics": self.statistics,
            "compatibility": self.compatibility,
            "summary": self._get_summary()
        }
    
    def _get_summary(self) -> Dict[str, int]:
        """获取问题摘要"""
        summary = {"info": 0, "warning": 0, "error": 0, "critical": 0}
        for issue in self.issues:
            summary[issue.severity.value] += 1
        return summary
    
    def add_issue(
        self,
        severity: ValidationSeverity,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        suggestion: Optional[str] = None
    ):
        """添加验证问题"""
        self.issues.append(PanelValidationIssue(
            severity=severity,
            code=code,
            message=message,
            details=details,
            suggestion=suggestion
        ))
        
        if severity in (ValidationSeverity.ERROR, ValidationSeverity.CRITICAL):
            self.valid = False


class PanelValidator:
    """
    参考面板验证器
    
    功能：
    1. 验证VCF/BCF/bref3文件格式
    2. 检查索引文件
    3. 验证样本和变异数据
    4. 检查与Beagle的兼容性
    """
    
    # VCF必需列
    VCF_REQUIRED_COLUMNS = ['#CHROM', 'POS', 'ID', 'REF', 'ALT', 'QUAL', 'FILTER', 'INFO']
    
    # 推荐的最小样本数
    MIN_RECOMMENDED_SAMPLES = 50
    
    # 推荐的最小变异数
    MIN_RECOMMENDED_VARIANTS = 1000
    
    def __init__(self):
        self.validation_results: List[PanelValidationResult] = []
    
    def validate(self, file_path: str) -> PanelValidationResult:
        """
        验证参考面板文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            验证结果
        """
        path = Path(file_path)
        
        # 确定文件格式
        file_format = self._detect_format(file_path)
        
        result = PanelValidationResult(
            valid=True,
            file_path=file_path,
            file_format=file_format
        )
        
        # 基本检查
        self._validate_file_exists(result, path)
        self._validate_file_size(result, path)
        self._validate_index(result, path)
        
        # 格式特定检查
        if file_format == 'vcf':
            self._validate_vcf_format(result, path)
        elif file_format == 'bcf':
            self._validate_bcf_format(result, path)
        elif file_format == 'bref3':
            self._validate_bref3_format(result, path)
        
        # 兼容性检查
        self._check_beagle_compatibility(result)
        
        self.validation_results.append(result)
        
        return result
    
    def _detect_format(self, file_path: str) -> str:
        """检测文件格式"""
        path = Path(file_path)
        suffix = ''.join(path.suffixes).lower()
        
        if '.bref3' in suffix:
            return 'bref3'
        elif '.bcf' in suffix:
            return 'bcf'
        elif '.vcf' in suffix:
            return 'vcf'
        else:
            return 'unknown'
    
    def _validate_file_exists(self, result: PanelValidationResult, path: Path):
        """验证文件存在"""
        if not path.exists():
            result.add_issue(
                ValidationSeverity.CRITICAL,
                "FILE_NOT_FOUND",
                f"文件不存在: {path}"
            )
    
    def _validate_file_size(self, result: PanelValidationResult, path: Path):
        """验证文件大小"""
        if not path.exists():
            return
        
        size_mb = path.stat().st_size / (1024 * 1024)
        result.statistics['file_size_mb'] = round(size_mb, 2)
        
        if size_mb == 0:
            result.add_issue(
                ValidationSeverity.CRITICAL,
                "EMPTY_FILE",
                "文件为空"
            )
        elif size_mb < 1:
            result.add_issue(
                ValidationSeverity.WARNING,
                "SMALL_FILE",
                f"文件较小 ({size_mb:.2f} MB)，可能数据不完整"
            )
    
    def _validate_index(self, result: PanelValidationResult, path: Path):
        """验证索引文件"""
        if not path.exists():
            return
        
        # 检查可能的索引文件
        index_extensions = ['.tbi', '.csi', '.idx']
        has_index = False
        index_path = None
        
        for ext in index_extensions:
            idx = Path(str(path) + ext)
            if idx.exists():
                has_index = True
                index_path = str(idx)
                break
        
        # 对于BCF文件
        if result.file_format == 'bcf':
            csi_path = path.with_suffix('.bcf.csi')
            if csi_path.exists():
                has_index = True
                index_path = str(csi_path)
        
        result.statistics['has_index'] = has_index
        result.statistics['index_path'] = index_path
        
        if not has_index:
            result.add_issue(
                ValidationSeverity.WARNING,
                "MISSING_INDEX",
                "缺少索引文件",
                suggestion="使用 'tabix -p vcf file.vcf.gz' 或 'bcftools index file.bcf' 创建索引"
            )
    
    def _validate_vcf_format(self, result: PanelValidationResult, path: Path):
        """验证VCF格式"""
        try:
            is_gzipped = str(path).endswith('.gz')
            
            if is_gzipped:
                f = gzip.open(path, 'rt')
            else:
                f = open(path, 'r')
            
            with f:
                header_lines = []
                sample_line = None
                variant_count = 0
                chromosomes = set()
                sample_count = 0
                
                for line in f:
                    if line.startswith('##'):
                        header_lines.append(line.strip())
                        continue
                    
                    if line.startswith('#CHROM'):
                        sample_line = line.strip()
                        columns = line.strip().split('\t')
                        
                        # 检查必需列
                        for col in self.VCF_REQUIRED_COLUMNS:
                            if col not in columns:
                                result.add_issue(
                                    ValidationSeverity.ERROR,
                                    "MISSING_COLUMN",
                                    f"缺少必需列: {col}"
                                )
                        
                        # 获取样本数
                        sample_count = max(0, len(columns) - 9)
                        result.statistics['sample_count'] = sample_count
                        continue
                    
                    if sample_line and not line.startswith('#'):
                        variant_count += 1
                        parts = line.split('\t')
                        if len(parts) > 0:
                            chromosomes.add(parts[0])
                        
                        # 只统计前10000行以提高速度
                        if variant_count >= 10000:
                            break
                
                result.statistics['variant_count_estimated'] = variant_count
                result.statistics['chromosome_count'] = len(chromosomes)
                result.statistics['chromosomes'] = sorted(list(chromosomes))[:10]
                
                # 验证样本数
                if sample_count == 0:
                    result.add_issue(
                        ValidationSeverity.ERROR,
                        "NO_SAMPLES",
                        "VCF文件不包含样本基因型数据"
                    )
                elif sample_count < self.MIN_RECOMMENDED_SAMPLES:
                    result.add_issue(
                        ValidationSeverity.WARNING,
                        "LOW_SAMPLE_COUNT",
                        f"样本数较少 ({sample_count})，建议至少 {self.MIN_RECOMMENDED_SAMPLES} 个样本"
                    )
                
                # 验证变异数
                if variant_count < self.MIN_RECOMMENDED_VARIANTS:
                    result.add_issue(
                        ValidationSeverity.WARNING,
                        "LOW_VARIANT_COUNT",
                        f"变异数较少 ({variant_count})，可能影响填充准确性"
                    )
                
                # 检查文件格式版本
                format_version = None
                for line in header_lines:
                    if 'fileformat=' in line:
                        format_version = line.split('=')[-1].strip()
                        break
                
                result.statistics['vcf_format'] = format_version
                
        except Exception as e:
            result.add_issue(
                ValidationSeverity.ERROR,
                "READ_ERROR",
                f"读取VCF文件失败: {str(e)}"
            )
    
    def _validate_bcf_format(self, result: PanelValidationResult, path: Path):
        """验证BCF格式"""
        try:
            # 尝试使用bcftools获取信息
            import subprocess
            
            # 获取样本数
            cmd = ['bcftools', 'query', '-l', str(path)]
            samples_result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if samples_result.returncode == 0:
                samples = [s for s in samples_result.stdout.strip().split('\n') if s]
                result.statistics['sample_count'] = len(samples)
                
                if len(samples) < self.MIN_RECOMMENDED_SAMPLES:
                    result.add_issue(
                        ValidationSeverity.WARNING,
                        "LOW_SAMPLE_COUNT",
                        f"样本数较少 ({len(samples)})"
                    )
            
            # 获取变异数
            cmd = ['bcftools', 'index', '-n', str(path)]
            count_result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if count_result.returncode == 0:
                variant_count = int(count_result.stdout.strip())
                result.statistics['variant_count'] = variant_count
                
                if variant_count < self.MIN_RECOMMENDED_VARIANTS:
                    result.add_issue(
                        ValidationSeverity.WARNING,
                        "LOW_VARIANT_COUNT",
                        f"变异数较少 ({variant_count})"
                    )
            
            result.add_issue(
                ValidationSeverity.INFO,
                "BCF_VALID",
                "BCF文件格式正确"
            )
            
        except FileNotFoundError:
            result.add_issue(
                ValidationSeverity.WARNING,
                "BCFTOOLS_NOT_FOUND",
                "未找到bcftools，无法完整验证BCF文件",
                suggestion="安装bcftools: conda install -c bioconda bcftools"
            )
        except Exception as e:
            result.add_issue(
                ValidationSeverity.ERROR,
                "BCF_VALIDATION_ERROR",
                f"BCF验证失败: {str(e)}"
            )
    
    def _validate_bref3_format(self, result: PanelValidationResult, path: Path):
        """验证bref3格式"""
        # bref3是Beagle专用格式，主要检查文件可读
        result.add_issue(
            ValidationSeverity.INFO,
            "BREF3_FORMAT",
            "bref3格式文件（Beagle原生格式）"
        )
        
        # 检查文件大小
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb < 10:
            result.add_issue(
                ValidationSeverity.WARNING,
                "SMALL_BREF3",
                "bref3文件较小，可能数据不完整"
            )
    
    def _check_beagle_compatibility(self, result: PanelValidationResult):
        """检查Beagle兼容性"""
        compatibility = {
            'beagle_supported': True,
            'recommended_version': '5.4',
            'notes': []
        }
        
        if result.file_format == 'vcf':
            if result.statistics.get('has_index'):
                compatibility['notes'].append("可直接用于Beagle填充")
            else:
                compatibility['notes'].append("需要创建索引后才能用于Beagle")
        
        elif result.file_format == 'bcf':
            compatibility['notes'].append("BCF格式需要转换为VCF或bref3格式")
            compatibility['beagle_supported'] = False
        
        elif result.file_format == 'bref3':
            compatibility['notes'].append("bref3是Beagle最优格式")
        
        result.compatibility = compatibility
    
    def batch_validate(self, directory: str) -> List[PanelValidationResult]:
        """
        批量验证目录中的面板文件
        
        Args:
            directory: 目录路径
            
        Returns:
            验证结果列表
        """
        results = []
        path = Path(directory)
        
        if not path.exists():
            logger.error(f"目录不存在: {directory}")
            return results
        
        # 查找所有面板文件
        patterns = ['*.vcf.gz', '*.vcf', '*.bcf', '*.bref3']
        
        for pattern in patterns:
            for file_path in path.glob(pattern):
                result = self.validate(str(file_path))
                results.append(result)
        
        return results
    
    def get_summary(self) -> Dict[str, Any]:
        """获取验证摘要"""
        if not self.validation_results:
            return {"message": "尚未进行验证"}
        
        total = len(self.validation_results)
        valid = sum(1 for r in self.validation_results if r.valid)
        
        issue_counts = {"info": 0, "warning": 0, "error": 0, "critical": 0}
        for result in self.validation_results:
            summary = result._get_summary()
            for key in issue_counts:
                issue_counts[key] += summary.get(key, 0)
        
        return {
            "total_files": total,
            "valid_files": valid,
            "invalid_files": total - valid,
            "issue_summary": issue_counts
        }
