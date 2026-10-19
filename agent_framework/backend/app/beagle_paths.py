"""
Beagle JAR 与参考面板 VCF 路径解析（与迁移 / .env 对齐）。

优先顺序：
1. settings.beagle_jar_path（若文件存在）
2. {refpanel_path}/beagle.jar
3. 系统常见路径
"""

from __future__ import annotations

import os
from typing import List, Optional

from app.config import settings


def resolve_beagle_jar() -> Optional[str]:
    """返回可用的 beagle.jar 绝对路径，找不到则 None。"""
    candidates: List[str] = []
    explicit = settings.beagle_jar_path
    if explicit and str(explicit).strip():
        candidates.append(os.path.abspath(str(explicit).strip()))
    rp = (settings.refpanel_path or "").rstrip("/")
    if rp:
        candidates.append(os.path.join(rp, "beagle.jar"))
    candidates.extend(
        [
            "/usr/local/bin/beagle.jar",
            "/opt/beagle/beagle.jar",
        ]
    )
    seen = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        if os.path.isfile(path):
            return path
    return None


def default_ref_panel_vcf_path() -> str:
    """与历史逻辑一致的默认参考 VCF 文件名（位于 refpanel_path 下）。"""
    rp = (settings.refpanel_path or "").rstrip("/")
    return os.path.join(
        rp,
        "2063.10.14.imiss0.2.panel.plink_ph.AN_AC.reiid.vcf.gz",
    )


def resolve_ref_panel_vcf() -> Optional[str]:
    """若默认参考 VCF 存在则返回路径，否则 None。"""
    p = default_ref_panel_vcf_path()
    return p if os.path.isfile(p) else None
