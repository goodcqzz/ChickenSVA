#!/usr/bin/env python3
"""
参考面板管理器 - 统一管理参考面板的发现、加载和元数据
支持多种格式的参考面板和自动索引管理
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime

import pandas as pd


def _project_root() -> Path:
    """推断仓库根目录（panel_manager.py 位于 repo/refpanel/）"""
    return Path(__file__).resolve().parent.parent


logger = logging.getLogger(__name__)


@dataclass
class PanelInfo:
    """参考面板信息"""
    id: str
    name: str
    description: str
    file_path: str
    file_size_mb: float
    sample_count: int
    variant_count: int
    chromosome_count: int
    has_index: bool
    index_path: Optional[str]
    format: str  # vcf, bref3, etc.
    created_at: str
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PanelManager:
    """
    参考面板管理器
    
    功能：
    1. 自动发现参考面板文件
    2. 提取面板元数据
    3. 管理面板索引
    4. 提供面板查询接口
    """
    
    # 支持的文件格式
    SUPPORTED_FORMATS = {
        '.vcf.gz': 'vcf',
        '.vcf': 'vcf',
        '.bref3': 'bref3',
        '.bcf': 'bcf'
    }
    
    # 索引文件扩展名
    INDEX_EXTENSIONS = ['.tbi', '.csi', '.idx']
    
    def __init__(
        self,
        refpanel_dir: str = "",
        auto_scan: bool = True
    ):
        if not refpanel_dir:
            refpanel_dir = str(_project_root() / "refpanel")
        self.refpanel_dir = Path(refpanel_dir)
        self.panels: Dict[str, PanelInfo] = {}
        self._metadata_cache: Dict[str, Any] = {}
        
        if auto_scan:
            self.scan_panels()
    
    def scan_panels(self) -> List[PanelInfo]:
        """
        扫描目录中的参考面板文件
        
        Returns:
            发现的面板列表
        """
        self.panels.clear()
        
        if not self.refpanel_dir.exists():
            logger.warning(f"参考面板目录不存在: {self.refpanel_dir}")
            return []
        
        logger.info(f"扫描参考面板目录: {self.refpanel_dir}")
        
        for file_path in self.refpanel_dir.iterdir():
            if file_path.is_file():
                panel = self._process_panel_file(file_path)
                if panel:
                    self.panels[panel.id] = panel
                    logger.info(f"✓ 发现参考面板: {panel.name} ({panel.sample_count} 样本)")
        
        logger.info(f"扫描完成，共发现 {len(self.panels)} 个参考面板")
        return list(self.panels.values())
    
    def _process_panel_file(self, file_path: Path) -> Optional[PanelInfo]:
        """处理单个面板文件"""
        # 跳过索引文件
        if any(str(file_path).endswith(ext) for ext in self.INDEX_EXTENSIONS):
            return None
        
        # 检查格式
        file_ext = ''.join(file_path.suffixes)
        if file_ext not in self.SUPPORTED_FORMATS:
            file_ext = file_path.suffix
            if file_ext not in self.SUPPORTED_FORMATS:
                return None
        
        format_type = self.SUPPORTED_FORMATS[file_ext]
        
        # 生成面板ID
        panel_id = self._generate_panel_id(file_path)
        
        # 提取元数据
        metadata = self._extract_metadata(file_path)
        
        # 检查索引
        has_index, index_path = self._check_index(file_path)
        
        # 获取文件信息
        stat = file_path.stat()
        
        return PanelInfo(
            id=panel_id,
            name=self._generate_panel_name(file_path),
            description=self._generate_description(file_path, metadata),
            file_path=str(file_path),
            file_size_mb=round(stat.st_size / (1024 * 1024), 2),
            sample_count=metadata.get('sample_count', 0),
            variant_count=metadata.get('variant_count', 0),
            chromosome_count=metadata.get('chromosome_count', 0),
            has_index=has_index,
            index_path=index_path,
            format=format_type,
            created_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
            metadata=metadata
        )
    
    def _generate_panel_id(self, file_path: Path) -> str:
        """生成面板唯一ID"""
        # 使用文件名（不含扩展名）作为ID
        name = file_path.stem
        if name.endswith('.vcf'):
            name = name[:-4]
        return re.sub(r'[^\w]', '_', name)
    
    def _generate_panel_name(self, file_path: Path) -> str:
        """生成面板显示名称"""
        # 从文件名提取信息
        name = file_path.stem
        
        # 尝试提取样本数
        match = re.search(r'(\d+)', name)
        if match:
            sample_count = match.group(1)
            return f"鸡参考面板 ({sample_count}样本)"
        
        return f"参考面板: {name}"
    
    def _generate_description(
        self,
        file_path: Path,
        metadata: Dict[str, Any]
    ) -> str:
        """生成面板描述"""
        parts = []
        
        if metadata.get('sample_count'):
            parts.append(f"{metadata['sample_count']}个样本")
        
        if metadata.get('variant_count'):
            parts.append(f"{metadata['variant_count']}个变异")
        
        if metadata.get('chromosome_count'):
            parts.append(f"覆盖{metadata['chromosome_count']}条染色体")
        
        if parts:
            return "，".join(parts)
        
        return f"参考面板文件: {file_path.name}"
    
    def _extract_metadata(self, file_path: Path) -> Dict[str, Any]:
        """从VCF文件提取元数据"""
        metadata = {
            'sample_count': 0,
            'variant_count': 0,
            'chromosome_count': 0,
            'chromosomes': [],
            'file_format': None
        }
        
        try:
            import gzip
            
            is_gzipped = str(file_path).endswith('.gz')
            
            if is_gzipped:
                f = gzip.open(file_path, 'rt')
            else:
                f = open(file_path, 'r')
            
            with f:
                sample_line = None
                variant_count = 0
                chromosomes = set()
                
                for line in f:
                    if line.startswith('##'):
                        # 解析头部元数据
                        if 'fileformat=' in line:
                            metadata['file_format'] = line.split('=')[-1].strip()
                        continue
                    
                    if line.startswith('#CHROM'):
                        sample_line = line.strip()
                        continue
                    
                    if sample_line and not line.startswith('#'):
                        variant_count += 1
                        chromosomes.add(line.split('\t')[0])
                        
                        # 只统计前10000行以提高速度
                        if variant_count >= 10000:
                            break
                
                # 解析样本数
                if sample_line:
                    columns = sample_line.split('\t')
                    # VCF格式：前9列为元数据，之后为样本
                    metadata['sample_count'] = max(0, len(columns) - 9)
                
                metadata['variant_count'] = variant_count
                metadata['chromosome_count'] = len(chromosomes)
                metadata['chromosomes'] = sorted(list(chromosomes))[:10]  # 只保存前10个
                
        except Exception as e:
            logger.warning(f"提取元数据失败 {file_path}: {e}")
        
        return metadata
    
    def _check_index(self, file_path: Path) -> Tuple[bool, Optional[str]]:
        """检查索引文件是否存在"""
        for ext in self.INDEX_EXTENSIONS:
            index_path = Path(str(file_path) + ext)
            if index_path.exists():
                return True, str(index_path)
        
        # 对于bcf文件检查.csi索引
        if str(file_path).endswith('.bcf'):
            csi_path = file_path.with_suffix('.bcf.csi')
            if csi_path.exists():
                return True, str(csi_path)
        
        return False, None
    
    def get_panel(self, panel_id: str) -> Optional[PanelInfo]:
        """获取指定面板信息"""
        return self.panels.get(panel_id)
    
    def get_all_panels(self) -> List[PanelInfo]:
        """获取所有面板"""
        return list(self.panels.values())
    
    def get_panel_list(self) -> List[Dict[str, Any]]:
        """获取面板列表（用于API返回）"""
        return [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "sample_count": p.sample_count,
                "variant_count": p.variant_count,
                "file_size_mb": p.file_size_mb,
                "has_index": p.has_index,
                "format": p.format
            }
            for p in self.panels.values()
        ]
    
    def get_recommended_panel(self, target_samples: int = 0) -> Optional[PanelInfo]:
        """
        获取推荐的参考面板
        
        Args:
            target_samples: 目标样本数，用于选择合适大小的面板
            
        Returns:
            推荐的面板信息
        """
        if not self.panels:
            return None
        
        # 优先选择有索引的面板
        indexed_panels = [p for p in self.panels.values() if p.has_index]
        
        if indexed_panels:
            # 选择样本数最多的
            return max(indexed_panels, key=lambda p: p.sample_count)
        
        # 否则选择样本数最多的
        return max(self.panels.values(), key=lambda p: p.sample_count)
    
    def create_index(self, panel_id: str) -> bool:
        """
        为面板创建索引
        
        Args:
            panel_id: 面板ID
            
        Returns:
            是否成功
        """
        panel = self.panels.get(panel_id)
        if not panel:
            logger.error(f"面板不存在: {panel_id}")
            return False
        
        if panel.has_index:
            logger.info(f"面板已有索引: {panel_id}")
            return True
        
        try:
            import subprocess
            
            file_path = panel.file_path
            
            if file_path.endswith('.vcf.gz'):
                # 使用tabix创建索引
                cmd = ['tabix', '-p', 'vcf', file_path]
                subprocess.run(cmd, check=True, capture_output=True)
                
                # 更新面板信息
                panel.has_index = True
                panel.index_path = file_path + '.tbi'
                
                logger.info(f"✓ 索引创建成功: {panel_id}")
                return True
                
            elif file_path.endswith('.bcf'):
                # 使用bcftools创建索引
                cmd = ['bcftools', 'index', file_path]
                subprocess.run(cmd, check=True, capture_output=True)
                
                panel.has_index = True
                panel.index_path = file_path + '.csi'
                
                logger.info(f"✓ 索引创建成功: {panel_id}")
                return True
            
            else:
                logger.warning(f"不支持的文件格式: {file_path}")
                return False
                
        except Exception as e:
            logger.error(f"创建索引失败: {e}")
            return False
    
    def validate_panel(self, panel_id: str) -> Dict[str, Any]:
        """
        验证面板文件
        
        Args:
            panel_id: 面板ID
            
        Returns:
            验证结果
        """
        panel = self.panels.get(panel_id)
        if not panel:
            return {"valid": False, "error": "面板不存在"}
        
        issues = []
        
        # 检查文件存在
        if not Path(panel.file_path).exists():
            issues.append({"level": "error", "message": "面板文件不存在"})
        
        # 检查索引
        if not panel.has_index:
            issues.append({
                "level": "warning",
                "message": "缺少索引文件",
                "suggestion": "运行 create_index 创建索引"
            })
        
        # 检查样本数
        if panel.sample_count < 10:
            issues.append({
                "level": "warning",
                "message": f"样本数较少 ({panel.sample_count})"
            })
        
        return {
            "valid": len([i for i in issues if i['level'] == 'error']) == 0,
            "panel_id": panel_id,
            "issues": issues,
            "metadata": panel.metadata
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取面板统计信息"""
        if not self.panels:
            return {"message": "没有可用的参考面板"}
        
        total_size = sum(p.file_size_mb for p in self.panels.values())
        total_samples = sum(p.sample_count for p in self.panels.values())
        
        return {
            "total_panels": len(self.panels),
            "total_size_mb": round(total_size, 2),
            "total_samples": total_samples,
            "indexed_panels": sum(1 for p in self.panels.values() if p.has_index),
            "formats": list(set(p.format for p in self.panels.values())),
            "panels": [
                {"id": p.id, "name": p.name, "samples": p.sample_count}
                for p in self.panels.values()
            ]
        }
