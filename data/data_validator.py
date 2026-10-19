#!/usr/bin/env python3
"""
数据验证器 - 提供数据质量检查和验证功能
支持SV数据、表型数据、VCF文件的验证
"""

import os
import gzip
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class ValidationLevel(Enum):
    """验证级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# 别名，用于向后兼容
ValidationSeverity = ValidationLevel


@dataclass
class ValidationIssue:
    """验证问题"""
    level: ValidationLevel
    message: str
    field: Optional[str] = None
    row: Optional[int] = None
    suggestion: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.value,
            "message": self.message,
            "field": self.field,
            "row": self.row,
            "suggestion": self.suggestion
        }


@dataclass
class ValidationResult:
    """验证结果"""
    valid: bool
    file_path: str
    file_type: str
    total_rows: int = 0
    issues: List[ValidationIssue] = field(default_factory=list)
    statistics: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "file_path": self.file_path,
            "file_type": self.file_type,
            "total_rows": self.total_rows,
            "issues": [i.to_dict() for i in self.issues],
            "statistics": self.statistics,
            "issue_summary": self._get_issue_summary()
        }
    
    def _get_issue_summary(self) -> Dict[str, int]:
        """获取问题摘要"""
        summary = {"info": 0, "warning": 0, "error": 0, "critical": 0}
        for issue in self.issues:
            summary[issue.level.value] += 1
        return summary
    
    def add_issue(
        self,
        level: ValidationLevel,
        message: str,
        field: Optional[str] = None,
        row: Optional[int] = None,
        suggestion: Optional[str] = None
    ):
        """添加验证问题"""
        self.issues.append(ValidationIssue(
            level=level,
            message=message,
            field=field,
            row=row,
            suggestion=suggestion
        ))
        
        # 如果有error或critical，标记为无效
        if level in (ValidationLevel.ERROR, ValidationLevel.CRITICAL):
            self.valid = False


class DataValidator:
    """
    数据验证器
    
    功能：
    1. SV频率数据验证
    2. 表型数据验证
    3. VCF文件验证
    4. 参考面板验证
    """
    
    # SV数据必需列
    SV_REQUIRED_COLUMNS = ['ID', 'Chr', 'POS']
    SV_OPTIONAL_COLUMNS = ['End', 'REF', 'ALT', 'SV_Type', 'Region', 'Gene', 'Mean_fre']
    
    # 有效的SV类型
    VALID_SV_TYPES = {'DEL', 'DUP', 'INV', 'INS', 'BND', 'CNV'}
    
    # VCF必需列
    VCF_REQUIRED_COLUMNS = ['#CHROM', 'POS', 'ID', 'REF', 'ALT', 'QUAL', 'FILTER', 'INFO']
    
    def __init__(self):
        self.validation_results: List[ValidationResult] = []
    
    def validate_sv_file(self, file_path: str) -> ValidationResult:
        """
        验证SV频率数据文件
        
        Args:
            file_path: CSV文件路径
            
        Returns:
            验证结果
        """
        result = ValidationResult(
            valid=True,
            file_path=file_path,
            file_type="SV_frequency"
        )
        
        try:
            path = Path(file_path)
            
            # 检查文件存在
            if not path.exists():
                result.add_issue(
                    ValidationLevel.CRITICAL,
                    f"文件不存在: {file_path}"
                )
                return result
            
            # 检查文件大小
            file_size = path.stat().st_size
            if file_size == 0:
                result.add_issue(
                    ValidationLevel.CRITICAL,
                    "文件为空"
                )
                return result
            
            result.statistics['file_size_mb'] = round(file_size / (1024 * 1024), 2)
            
            # 尝试读取文件
            try:
                df = pd.read_csv(file_path)
                result.total_rows = len(df)
            except Exception as e:
                result.add_issue(
                    ValidationLevel.CRITICAL,
                    f"无法读取文件: {str(e)}",
                    suggestion="检查文件编码格式，尝试使用UTF-8或GBK编码"
                )
                return result
            
            # 检查必需列
            columns = [str(col).strip() for col in df.columns]
            for col in self.SV_REQUIRED_COLUMNS:
                if col not in columns:
                    result.add_issue(
                        ValidationLevel.ERROR,
                        f"缺少必需列: {col}",
                        suggestion=f"确保CSV文件包含列: {col}"
                    )
            
            # 检查数据类型
            if 'POS' in columns:
                pos_numeric = pd.to_numeric(df['POS'], errors='coerce')
                null_count = pos_numeric.isna().sum()
                if null_count > 0:
                    result.add_issue(
                        ValidationLevel.WARNING,
                        f"位置列包含 {null_count} 个非数值",
                        field="POS"
                    )
            
            # 检查SV类型
            if 'SV_Type' in columns:
                sv_types = df['SV_Type'].dropna().str.upper().unique()
                invalid_types = set(sv_types) - self.VALID_SV_TYPES
                if invalid_types:
                    result.add_issue(
                        ValidationLevel.WARNING,
                        f"发现未知SV类型: {invalid_types}",
                        field="SV_Type",
                        suggestion=f"有效的SV类型: {self.VALID_SV_TYPES}"
                    )
            
            # 检查频率值
            breed_start_idx = 10 if 'Mean_fre' in columns else 8
            breed_cols = columns[breed_start_idx:]
            
            invalid_freq_count = 0
            for col in breed_cols[:10]:  # 只检查前10个品种列
                if col in df.columns:
                    numeric_col = pd.to_numeric(df[col], errors='coerce')
                    invalid = ((numeric_col < 0) | (numeric_col > 1)).sum()
                    invalid_freq_count += invalid
            
            if invalid_freq_count > 0:
                result.add_issue(
                    ValidationLevel.WARNING,
                    f"发现 {invalid_freq_count} 个无效频率值（应在0-1之间）",
                    suggestion="检查频率数据是否正确归一化"
                )
            
            # 统计信息
            result.statistics['columns'] = len(columns)
            result.statistics['breed_columns'] = len(breed_cols)
            result.statistics['sv_types'] = list(sv_types) if 'SV_Type' in columns else []
            
            logger.info(f"✓ SV文件验证完成: {path.name}, {result.total_rows} 行")
            
        except Exception as e:
            result.add_issue(
                ValidationLevel.CRITICAL,
                f"验证过程出错: {str(e)}"
            )
        
        return result
    
    def validate_phenotype_file(self, file_path: str) -> ValidationResult:
        """
        验证表型数据文件
        
        Args:
            file_path: CSV文件路径
            
        Returns:
            验证结果
        """
        result = ValidationResult(
            valid=True,
            file_path=file_path,
            file_type="phenotype"
        )
        
        try:
            path = Path(file_path)
            
            if not path.exists():
                result.add_issue(
                    ValidationLevel.CRITICAL,
                    f"文件不存在: {file_path}"
                )
                return result
            
            # 读取文件
            try:
                df = pd.read_csv(file_path)
                result.total_rows = len(df)
            except Exception as e:
                result.add_issue(
                    ValidationLevel.CRITICAL,
                    f"无法读取文件: {str(e)}"
                )
                return result
            
            # 检查列数
            if len(df.columns) < 2:
                result.add_issue(
                    ValidationLevel.ERROR,
                    "表型数据至少需要2列（性状+至少1个品种）"
                )
                return result
            
            # 检查品种列
            breed_count = len(df.columns) - 1
            result.statistics['breed_count'] = breed_count
            
            if breed_count < 5:
                result.add_issue(
                    ValidationLevel.WARNING,
                    f"品种数量较少 ({breed_count})，可能影响关联分析准确性"
                )
            
            # 检查缺失值
            null_counts = df.isnull().sum()
            high_null_cols = null_counts[null_counts > len(df) * 0.5]
            if not high_null_cols.empty:
                result.add_issue(
                    ValidationLevel.WARNING,
                    f"以下列缺失值超过50%: {list(high_null_cols.index)}"
                )
            
            result.statistics['traits'] = result.total_rows
            
            logger.info(f"✓ 表型文件验证完成: {path.name}, {breed_count} 个品种")
            
        except Exception as e:
            result.add_issue(
                ValidationLevel.CRITICAL,
                f"验证过程出错: {str(e)}"
            )
        
        return result
    
    def validate_vcf_file(self, file_path: str) -> ValidationResult:
        """
        验证VCF文件
        
        Args:
            file_path: VCF文件路径
            
        Returns:
            验证结果
        """
        result = ValidationResult(
            valid=True,
            file_path=file_path,
            file_type="VCF"
        )
        
        try:
            path = Path(file_path)
            
            if not path.exists():
                result.add_issue(
                    ValidationLevel.CRITICAL,
                    f"文件不存在: {file_path}"
                )
                return result
            
            # 检查索引文件
            index_file = Path(str(file_path) + '.tbi')
            if not index_file.exists():
                result.add_issue(
                    ValidationLevel.WARNING,
                    "缺少索引文件 (.tbi)",
                    suggestion="使用 tabix 创建索引: tabix -p vcf file.vcf.gz"
                )
            
            # 读取VCF头部
            is_gzipped = file_path.endswith('.gz')
            
            try:
                if is_gzipped:
                    with gzip.open(file_path, 'rt') as f:
                        header_lines = []
                        for line in f:
                            if line.startswith('#'):
                                header_lines.append(line)
                            else:
                                break
                else:
                    with open(file_path, 'r') as f:
                        header_lines = []
                        for line in f:
                            if line.startswith('#'):
                                header_lines.append(line)
                            else:
                                break
                
                # 检查头部
                if not header_lines:
                    result.add_issue(
                        ValidationLevel.ERROR,
                        "VCF文件缺少头部信息"
                    )
                    return result
                
                # 检查最后一行头部（列名）
                header_line = [l for l in header_lines if l.startswith('#CHROM')]
                if not header_line:
                    result.add_issue(
                        ValidationLevel.ERROR,
                        "VCF文件缺少#CHROM头部行"
                    )
                    return result
                
                columns = header_line[0].strip().split('\t')
                
                # 检查必需列
                for col in self.VCF_REQUIRED_COLUMNS:
                    if col not in columns:
                        result.add_issue(
                            ValidationLevel.ERROR,
                            f"VCF缺少必需列: {col}"
                        )
                
                # 检查样本列
                sample_count = len(columns) - 9
                result.statistics['sample_count'] = sample_count
                
                if sample_count == 0:
                    result.add_issue(
                        ValidationLevel.WARNING,
                        "VCF文件不包含样本基因型数据"
                    )
                
                result.statistics['columns'] = columns[:9]  # 只保存元数据列
                
            except Exception as e:
                result.add_issue(
                    ValidationLevel.CRITICAL,
                    f"读取VCF文件失败: {str(e)}"
                )
            
            logger.info(f"✓ VCF文件验证完成: {path.name}")
            
        except Exception as e:
            result.add_issue(
                ValidationLevel.CRITICAL,
                f"验证过程出错: {str(e)}"
            )
        
        return result
    
    def validate_reference_panel(self, file_path: str) -> ValidationResult:
        """
        验证参考面板文件
        
        Args:
            file_path: 参考面板VCF路径
            
        Returns:
            验证结果
        """
        result = self.validate_vcf_file(file_path)
        result.file_type = "reference_panel"
        
        # 额外的参考面板检查
        if result.valid:
            result.add_issue(
                ValidationLevel.INFO,
                "参考面板格式正确",
                suggestion="可以使用该面板进行基因型填充"
            )
        
        return result
    
    def validate_file(self, file_path: str) -> ValidationResult:
        """
        通用文件验证方法
        
        Args:
            file_path: 文件路径
            
        Returns:
            验证结果
        """
        path = Path(file_path)
        
        # 检查文件是否存在
        if not path.exists():
            return ValidationResult(
                valid=False,
                file_path=file_path,
                file_type="unknown",
                issues=[ValidationIssue(
                    level=ValidationLevel.CRITICAL,
                    message=f"文件不存在: {file_path}"
                )]
            )
        
        # 根据扩展名选择验证方法
        suffix = ''.join(path.suffixes).lower()
        name_lower = path.name.lower()
        
        if suffix == '.csv':
            # 根据文件名判断类型
            if 'phenotype' in name_lower or '表型' in name_lower:
                return self.validate_phenotype_file(file_path)
            else:
                return self.validate_sv_file(file_path)
        elif suffix in ('.vcf', '.vcf.gz'):
            return self.validate_vcf_file(file_path)
        else:
            # 未知类型，返回基本信息
            return ValidationResult(
                valid=True,
                file_path=file_path,
                file_type="unknown",
                issues=[ValidationIssue(
                    level=ValidationLevel.INFO,
                    message=f"未识别的文件类型: {suffix}"
                )]
            )
    
    def batch_validate(
        self,
        data_dir: str,
        file_extensions: Optional[List[str]] = None
    ) -> List[ValidationResult]:
        """
        批量验证目录中的文件
        
        Args:
            data_dir: 数据目录
            file_extensions: 要验证的文件扩展名列表
            
        Returns:
            验证结果列表
        """
        results = []
        path = Path(data_dir)
        
        if not path.exists():
            logger.error(f"目录不存在: {data_dir}")
            return results
        
        extensions = file_extensions or ['.csv', '.vcf', '.vcf.gz']
        
        for ext in extensions:
            for file_path in path.glob(f'*{ext}'):
                result = self.validate_file(str(file_path))
                results.append(result)
        
        self.validation_results = results
        return results
    
    def get_summary(self) -> Dict[str, Any]:
        """获取验证摘要"""
        if not self.validation_results:
            return {"message": "尚未进行验证"}
        
        total_files = len(self.validation_results)
        valid_files = sum(1 for r in self.validation_results if r.valid)
        
        issue_counts = {"info": 0, "warning": 0, "error": 0, "critical": 0}
        for result in self.validation_results:
            summary = result._get_issue_summary()
            for key in issue_counts:
                issue_counts[key] += summary.get(key, 0)
        
        return {
            "total_files": total_files,
            "valid_files": valid_files,
            "invalid_files": total_files - valid_files,
            "issue_summary": issue_counts
        }
