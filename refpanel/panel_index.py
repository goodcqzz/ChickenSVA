#!/usr/bin/env python3
"""
参考面板索引管理器 - 管理参考面板的索引创建和查询
支持多种索引格式：TBI、CSI、bref3
"""

import os
import subprocess
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class IndexInfo:
    """索引信息"""
    file_path: str
    index_type: str  # tbi, csi, bref3
    created_at: Optional[str] = None
    file_size_mb: float = 0.0
    is_valid: bool = False


class PanelIndex:
    """
    参考面板索引管理器
    
    功能：
    1. 自动检测和创建索引
    2. 支持TBI、CSI、bref3格式
    3. 索引有效性验证
    4. 索引性能统计
    """
    
    def __init__(self):
        self.index_cache: Dict[str, IndexInfo] = {}
    
    def check_index(self, file_path: str) -> Optional[IndexInfo]:
        """
        检查文件索引状态
        
        Args:
            file_path: 面板文件路径
            
        Returns:
            索引信息，如果没有索引则返回None
        """
        path = Path(file_path)
        
        if not path.exists():
            return None
        
        # 检查各种索引格式
        index_checks = [
            (f"{file_path}.tbi", "tbi"),
            (f"{file_path}.csi", "csi"),
            (f"{file_path}.idx", "idx"),
        ]
        
        # BCF特殊处理
        if file_path.endswith('.bcf'):
            index_checks.insert(0, (str(path.with_suffix('.bcf.csi')), "csi"))
        
        for idx_path, idx_type in index_checks:
            if os.path.exists(idx_path):
                stat = os.stat(idx_path)
                return IndexInfo(
                    file_path=idx_path,
                    index_type=idx_type,
                    created_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    file_size_mb=round(stat.st_size / (1024 * 1024), 2),
                    is_valid=True
                )
        
        return None
    
    def create_index(
        self,
        file_path: str,
        index_type: Optional[str] = None,
        force: bool = False
    ) -> IndexInfo:
        """
        创建索引
        
        Args:
            file_path: 面板文件路径
            index_type: 索引类型 (tbi, csi)，None则自动选择
            force: 强制重新创建
            
        Returns:
            索引信息
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        # 检查现有索引
        existing = self.check_index(file_path)
        if existing and not force:
            logger.info(f"索引已存在: {existing.file_path}")
            return existing
        
        # 确定索引类型
        if not index_type:
            index_type = self._determine_index_type(file_path)
        
        # 创建索引
        if index_type == "tbi":
            return self._create_tbi_index(file_path)
        elif index_type == "csi":
            return self._create_csi_index(file_path)
        else:
            raise ValueError(f"不支持的索引类型: {index_type}")
    
    def _determine_index_type(self, file_path: str) -> str:
        """确定最佳索引类型"""
        # VCF.gz 使用 TBI
        if file_path.endswith('.vcf.gz'):
            return "tbi"
        
        # BCF 使用 CSI
        if file_path.endswith('.bcf'):
            return "csi"
        
        # 默认使用 TBI
        return "tbi"
    
    def _create_tbi_index(self, file_path: str) -> IndexInfo:
        """创建TBI索引"""
        try:
            cmd = ['tabix', '-p', 'vcf', file_path]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            
            index_path = f"{file_path}.tbi"
            
            if os.path.exists(index_path):
                stat = os.stat(index_path)
                info = IndexInfo(
                    file_path=index_path,
                    index_type="tbi",
                    created_at=datetime.now().isoformat(),
                    file_size_mb=round(stat.st_size / (1024 * 1024), 2),
                    is_valid=True
                )
                logger.info(f"✓ TBI索引创建成功: {index_path}")
                return info
            else:
                raise RuntimeError("索引文件未生成")
                
        except subprocess.CalledProcessError as e:
            logger.error(f"TBI索引创建失败: {e.stderr}")
            raise RuntimeError(f"tabix失败: {e.stderr}")
        except FileNotFoundError:
            logger.error("未找到tabix命令")
            raise RuntimeError("请安装tabix: conda install -c bioconda htslib")
    
    def _create_csi_index(self, file_path: str) -> IndexInfo:
        """创建CSI索引"""
        try:
            # 优先使用bcftools
            cmd = ['bcftools', 'index', file_path]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            
            # BCF文件索引在.bcf.csi
            if file_path.endswith('.bcf'):
                index_path = str(Path(file_path).with_suffix('.bcf.csi'))
            else:
                index_path = f"{file_path}.csi"
            
            if os.path.exists(index_path):
                stat = os.stat(index_path)
                info = IndexInfo(
                    file_path=index_path,
                    index_type="csi",
                    created_at=datetime.now().isoformat(),
                    file_size_mb=round(stat.st_size / (1024 * 1024), 2),
                    is_valid=True
                )
                logger.info(f"✓ CSI索引创建成功: {index_path}")
                return info
            else:
                raise RuntimeError("索引文件未生成")
                
        except subprocess.CalledProcessError as e:
            logger.error(f"CSI索引创建失败: {e.stderr}")
            raise RuntimeError(f"bcftools失败: {e.stderr}")
        except FileNotFoundError:
            logger.error("未找到bcftools命令")
            raise RuntimeError("请安装bcftools: conda install -c bioconda bcftools")
    
    def validate_index(self, file_path: str) -> Dict[str, Any]:
        """
        验证索引有效性
        
        Args:
            file_path: 面板文件路径
            
        Returns:
            验证结果
        """
        index_info = self.check_index(file_path)
        
        if not index_info:
            return {
                "valid": False,
                "message": "索引不存在"
            }
        
        # 尝试使用索引查询
        try:
            if index_info.index_type == "tbi":
                # 使用tabix测试查询
                cmd = ['tabix', '-l', file_path]
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0:
                    chromosomes = [c for c in result.stdout.strip().split('\n') if c]
                    return {
                        "valid": True,
                        "index_type": index_info.index_type,
                        "chromosomes": chromosomes[:10],
                        "message": "索引有效"
                    }
                else:
                    return {
                        "valid": False,
                        "message": f"索引测试失败: {result.stderr}"
                    }
            
            elif index_info.index_type == "csi":
                # 使用bcftools测试
                cmd = ['bcftools', 'index', '-s', file_path]
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0:
                    return {
                        "valid": True,
                        "index_type": index_info.index_type,
                        "message": "索引有效"
                    }
                else:
                    return {
                        "valid": False,
                        "message": f"索引测试失败: {result.stderr}"
                    }
            
        except Exception as e:
            return {
                "valid": False,
                "message": f"验证过程出错: {str(e)}"
            }
        
        return {
            "valid": True,
            "index_type": index_info.index_type,
            "message": "索引存在"
        }
    
    def remove_index(self, file_path: str) -> bool:
        """
        删除索引
        
        Args:
            file_path: 面板文件路径
            
        Returns:
            是否成功
        """
        index_info = self.check_index(file_path)
        
        if not index_info:
            return False
        
        try:
            os.remove(index_info.file_path)
            logger.info(f"索引已删除: {index_info.file_path}")
            return True
        except Exception as e:
            logger.error(f"删除索引失败: {e}")
            return False
    
    def get_index_stats(self, file_path: str) -> Dict[str, Any]:
        """
        获取索引统计信息
        
        Args:
            file_path: 面板文件路径
            
        Returns:
            统计信息
        """
        index_info = self.check_index(file_path)
        
        if not index_info:
            return {"indexed": False}
        
        path = Path(file_path)
        file_size = path.stat().st_size / (1024 * 1024)
        
        return {
            "indexed": True,
            "index_type": index_info.index_type,
            "index_size_mb": index_info.file_size_mb,
            "index_ratio": round(index_info.file_size_mb / file_size * 100, 2) if file_size > 0 else 0,
            "created_at": index_info.created_at
        }
