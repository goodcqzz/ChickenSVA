"""
工具通用辅助函数和数据加载器
"""

import logging
import os
import re
import sys
from typing import Any, List, Optional

import numpy as np
import pandas as pd

from app.config import settings
from app.paths import get_install_root, annotation_dir, data_dir

logger = logging.getLogger(__name__)

_INSTALL_ROOT = get_install_root()

# 添加 refpanel 到 Python 路径
REFPANEL_PATH = str(settings.refpanel_path or (_INSTALL_ROOT / "refpanel"))
if REFPANEL_PATH not in sys.path:
    sys.path.insert(0, REFPANEL_PATH)

# 添加 mcp 到 Python 路径
MCP_PATH = str(_INSTALL_ROOT / "mcp")
if MCP_PATH not in sys.path:
    sys.path.insert(0, MCP_PATH)

# 添加 annotation 到 Python 路径
ANNOTATION_PATH = str(annotation_dir())
if ANNOTATION_PATH not in sys.path:
    sys.path.insert(0, ANNOTATION_PATH)

# 尝试导入参考面板和 MCP 工具
try:
    from panel_manager import PanelManager
    from beagle_runner import BeagleRunner, ImputationConfig

    _refpanel_available = True
    logger.info("✓ 参考面板模块加载成功")
except ImportError as e:
    _refpanel_available = False
    logger.warning(f"⚠ 参考面板模块加载失败: {e}")

try:
    from chicken_sv_tool import ChickenSVTool

    _mcp_tool_available = True
    logger.info("✓ MCP ChickenSVTool加载成功")
except ImportError as e:
    _mcp_tool_available = False
    logger.warning(f"⚠ MCP工具加载失败: {e}")


# 全局 CSV 数据缓存
_csv_data: Optional[pd.DataFrame] = None
_csv_path: str = settings.csv_data_path
_phenotype_data: Optional[pd.DataFrame] = None
_phenotype_path: str = settings.phenotype_data_path


def _normalize_chrom(value: str) -> str:
    chrom = str(value).strip()
    if chrom.lower().startswith("chr"):
        chrom = chrom[3:]
    return chrom


def _load_csv_data() -> Optional[pd.DataFrame]:
    """加载 CSV 数据"""
    global _csv_data
    if _csv_data is None:
        if os.path.exists(_csv_path):
            try:
                _csv_data = pd.read_csv(_csv_path, encoding="utf-8", low_memory=False)
            except UnicodeDecodeError:
                _csv_data = pd.read_csv(_csv_path, encoding="gbk", low_memory=False)
            logging.info(f"CSV数据加载完成: {len(_csv_data)} 条记录")
        else:
            logging.error(f"CSV文件不存在: {_csv_path}")
    return _csv_data


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value)).strip().lower()


def _load_phenotype_data() -> Optional[pd.DataFrame]:
    global _phenotype_data
    if _phenotype_data is None:
        if os.path.exists(_phenotype_path):
            for encoding in ("utf-8", "gbk", "gb18030", "latin1"):
                try:
                    _phenotype_data = pd.read_csv(_phenotype_path, encoding=encoding)
                    _phenotype_data.columns = [str(c).strip() for c in _phenotype_data.columns]
                    break
                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    logger.debug(f"表型数据读取失败[{encoding}]: {e}")
                    continue
        else:
            logger.warning(f"表型文件不存在: {_phenotype_path}")
    return _phenotype_data


def _build_chicken_sv_tool(load_annotation: bool = False) -> Optional["ChickenSVTool"]:
    if not _mcp_tool_available:
        return None
    try:
        import chicken_sv_tool as cst_module
        from chicken_sv_tool import ChickenSVTool as _CST
        logger.info("ChickenSVTool module file: %s", getattr(cst_module, "__file__", "unknown"))
    except ImportError:
        logger.error("ChickenSVTool导入失败，无法构建MCP工具实例")
        return None
    annotation_path = str(annotation_dir() / "Gallus_gallus.bGalGal1.mat.broiler.GRCg7b.115.gff3")
    phenotype_path = str(data_dir() / "鸡种表型-2024.csv")
    resolved_annotation_path = annotation_path if (load_annotation and os.path.exists(annotation_path)) else None
    return _CST(
        data_path=str(data_dir()),
        annotation_path=resolved_annotation_path,
        phenotype_path=phenotype_path if os.path.exists(phenotype_path) else None,
    )


def _ensure_list(value: Any) -> Optional[List[str]]:
    if value is None or value == "":
        return None
    if isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value if str(item).strip()]
        return items or None
    if isinstance(value, str):
        parts = [part.strip() for part in re.split(r"[\s,;，；]+", value) if part.strip()]
        return parts or None
    text = str(value).strip()
    return [text] if text else None


def _extract_sv_id(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            if item:
                return str(item).strip()
        return ""
    if isinstance(value, dict):
        return str(value.get("sv_id") or value.get("id") or "").strip()
    return str(value).strip()


def _looks_like_sv_id(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(re.match(r"^\d+_.+_(DEL|DUP|INV|INS|BND)$", text, re.IGNORECASE))


# GFF3 解析器懒加载单例
_gff3_parser = None


def _get_gff3_parser():
    """获取 GFF3 解析器单例（懒加载）"""
    global _gff3_parser
    if _gff3_parser is None:
        try:
            from gff3_parser import GFF3Parser
            gff3_file = settings.annotation_gff3_path
            if os.path.exists(gff3_file):
                logger.info(f"正在加载 GFF3 索引: {gff3_file}")
                _gff3_parser = GFF3Parser(gff3_file, build_index=True, cache_records=False)
                stats = _gff3_parser.get_statistics()
                logger.info(f"GFF3 索引加载完成: {stats.get('gene_count', 0)} 个基因")
            else:
                logger.warning(f"GFF3 文件不存在: {gff3_file}")
        except Exception as e:
            logger.warning(f"GFF3 解析器加载失败: {e}")
    return _gff3_parser
