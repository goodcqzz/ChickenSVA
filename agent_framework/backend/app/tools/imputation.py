"""
基因型填充工作流工具集
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.tools.common import _refpanel_available
from app.config import settings
from app.beagle_paths import default_ref_panel_vcf_path, resolve_beagle_jar
from app.workspace_session_store import bind_session_workspace, get_workspace_for_session

logger = logging.getLogger(__name__)

WORKSPACE_BASE = settings.workspace_base_path
DEFAULT_MAX_UPLOAD_MB = settings.workspace_max_upload_mb


def _ensure_workspace_dirs(workspace_id: str) -> Dict[str, str]:
    dirs = {
        "root": f"{WORKSPACE_BASE}/{workspace_id}",
        "input": f"{WORKSPACE_BASE}/{workspace_id}/input",
        "output": f"{WORKSPACE_BASE}/{workspace_id}/output",
        "logs": f"{WORKSPACE_BASE}/{workspace_id}/logs",
    }
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    return dirs


async def _emit_workspace(registry, payload: Dict[str, Any], session_id: str = "") -> None:
    if session_id:
        payload = {**payload, "session_id": session_id}
    await registry.emit_event("workspace_activate", payload, session_id=session_id or None)


async def create_imputation_workspace(
    registry,
    workspace_type: str = "imputation",
    description: str = "",
    session_id: str = "",
) -> Dict[str, Any]:
    if session_id:
        existing = get_workspace_for_session(session_id)
        if existing:
            workspace_id = existing["workspace_id"]
            bound_type = existing.get("workspace_type") or workspace_type
            dirs = _ensure_workspace_dirs(workspace_id)
            await _emit_workspace(
                registry,
                {
                    "workspace_id": workspace_id,
                    "workspace_type": bound_type,
                    "description": description,
                    "reused": True,
                },
                session_id,
            )
            return {
                "status": "existing",
                "workspace_id": workspace_id,
                "workspace_type": bound_type,
                "description": description,
                "directories": dirs,
                "session_id": session_id,
                "created_at": existing.get("updated_at", datetime.utcnow().isoformat()),
                "message": f"当前对话已绑定工作区 {workspace_id}，无需重复创建。",
            }

    workspace_id = f"ws_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    dirs = _ensure_workspace_dirs(workspace_id)

    if session_id:
        bind_session_workspace(session_id, workspace_id, workspace_type)

    await _emit_workspace(
        registry,
        {
            "workspace_id": workspace_id,
            "workspace_type": workspace_type,
            "description": description,
        },
        session_id,
    )

    return {
        "status": "created",
        "workspace_id": workspace_id,
        "workspace_type": workspace_type,
        "description": description,
        "directories": dirs,
        "session_id": session_id or None,
        "created_at": datetime.utcnow().isoformat(),
        "message": f"工作区 {workspace_id} 已创建并与当前对话绑定，请在工作区面板上传数据文件（单文件 ≤ {DEFAULT_MAX_UPLOAD_MB}MB）。",
    }


async def request_file_upload(
    registry,
    workspace_id: str = "",
    file_types: str = "vcf,plink",
    max_size_mb: int = DEFAULT_MAX_UPLOAD_MB,
    session_id: str = "",
) -> Dict[str, Any]:
    await _emit_workspace(
        registry,
        {
            "workspace_id": workspace_id,
            "workspace_type": "imputation",
            "action": "request_upload",
            "file_types": file_types.split(","),
            "max_size_mb": max_size_mb,
        },
        session_id,
    )

    return {
        "status": "upload_requested",
        "workspace_id": workspace_id,
        "upload_endpoint": f"/api/v1/workspaces/{workspace_id}/upload",
        "accepted_formats": file_types.split(","),
        "max_size_mb": max_size_mb,
        "message": f"请在右侧工作区面板上传数据文件（单文件不超过 {max_size_mb}MB）。",
    }


async def validate_workspace_files(
    workspace_id: str = "",
    file_names: str = "",
) -> Dict[str, Any]:
    input_dir = f"{WORKSPACE_BASE}/{workspace_id}/input"
    files = os.listdir(input_dir) if os.path.exists(input_dir) else []

    errors = []
    warnings = []
    file_type = None

    for f in files:
        if not (f.endswith((".vcf", ".vcf.gz", ".bed", ".bim", ".fam"))):
            errors.append(f"不支持的文件格式: {f}")

    if not files:
        errors.append("输入目录中没有文件")

    vcf_files = [f for f in files if f.endswith((".vcf", ".vcf.gz"))]
    plink_files = [f for f in files if f.endswith((".bed", ".bim", ".fam"))]

    if vcf_files and plink_files:
        errors.append("不能同时上传VCF和PLINK格式文件，请选择一种格式")
    elif vcf_files:
        file_type = "vcf"
        if len(vcf_files) > 1:
            warnings.append(f"检测到多个VCF文件，将使用第一个: {vcf_files[0]}")
    elif plink_files:
        file_type = "plink"
        has_bed = any(f.endswith(".bed") for f in plink_files)
        has_bim = any(f.endswith(".bim") for f in plink_files)
        has_fam = any(f.endswith(".fam") for f in plink_files)
        if not (has_bed and has_bim and has_fam):
            missing = []
            if not has_bed:
                missing.append(".bed")
            if not has_bim:
                missing.append(".bim")
            if not has_fam:
                missing.append(".fam")
            errors.append(
                f"PLINK格式不完整，缺少以下文件: {', '.join(missing)}。"
                "请同时上传.bed, .bim, .fam三个文件"
            )
    else:
        if files:
            errors.append(
                "未检测到有效的基因型数据文件。请上传VCF(.vcf/.vcf.gz)或PLINK(.bed/.bim/.fam)格式文件"
            )

    return {
        "workspace_id": workspace_id,
        "is_valid": len(errors) == 0,
        "file_type": file_type,
        "files": files,
        "file_count": len(files),
        "errors": errors,
        "warnings": warnings,
    }


async def run_workspace_imputation(
    registry,
    workspace_id: str = "",
    input_file: str = "",
    ref_panel: str = "default",
    nthreads: int = 4,
    session_id: str = "",
) -> Dict[str, Any]:
    """执行基因型填充 - 使用真实Beagle和参考面板"""
    input_dir = f"{WORKSPACE_BASE}/{workspace_id}/input"
    output_dir = f"{WORKSPACE_BASE}/{workspace_id}/output"
    logs_dir = f"{WORKSPACE_BASE}/{workspace_id}/logs"

    if not os.path.exists(input_dir):
        return {"error": f"工作区不存在: {workspace_id}"}

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)

    files = os.listdir(input_dir)
    if not files:
        return {"error": "输入目录中没有文件，请先上传数据"}

    vcf_files = [f for f in files if f.endswith((".vcf", ".vcf.gz"))]
    plink_files = [f for f in files if f.endswith((".bed", ".bim", ".fam"))]

    if vcf_files and plink_files:
        return {"error": "不能同时包含VCF和PLINK格式文件，请只保留一种格式"}

    if plink_files:
        has_bed = any(f.endswith(".bed") for f in plink_files)
        has_bim = any(f.endswith(".bim") for f in plink_files)
        has_fam = any(f.endswith(".fam") for f in plink_files)
        if not (has_bed and has_bim and has_fam):
            missing = []
            if not has_bed:
                missing.append(".bed")
            if not has_bim:
                missing.append(".bim")
            if not has_fam:
                missing.append(".fam")
            return {
                "error": "PLINK格式文件不完整",
                "missing_files": missing,
                "message": f"缺少以下文件: {', '.join(missing)}。",
            }

    if not vcf_files and not plink_files:
        return {"error": "未找到有效的基因型数据文件(VCF或PLINK格式)"}

    task_id = f"task_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    await _emit_workspace(
        registry,
        {
            "workspace_id": workspace_id,
            "workspace_type": "imputation",
            "action": "imputation_started",
            "task_id": task_id,
        },
        session_id,
    )

    actual_input_file = input_file
    if not actual_input_file:
        if vcf_files:
            actual_input_file = vcf_files[0]
        else:
            bed_file = next((f for f in plink_files if f.endswith(".bed")), None)
            if bed_file:
                actual_input_file = bed_file.replace(".bed", "")

    ref_panel_path = default_ref_panel_vcf_path()
    ref_panel_available = os.path.exists(ref_panel_path)
    beagle_jar = resolve_beagle_jar()

    if _refpanel_available and ref_panel_available and vcf_files and beagle_jar:
        try:
            logger.info("使用真实Beagle填充: workspace=%s", workspace_id)

            input_path = os.path.join(input_dir, actual_input_file)
            output_prefix = os.path.join(output_dir, f"imputed_{task_id}")
            log_file = os.path.join(logs_dir, f"beagle_{task_id}.log")

            cmd = [
                "java",
                "-Xmx4096m",
                "-jar",
                beagle_jar,
                "gt=" + input_path,
                "ref=" + ref_panel_path,
                "out=" + output_prefix,
                "nthreads=" + str(min(nthreads, 2)),
                "window=40",
                "overlap=5",
                "impute=true",
                "gp=true",
            ]

            logger.info("Beagle命令: %s", " ".join(cmd))

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async def _monitor_beagle(
                proc: asyncio.subprocess.Process,
                ws_id: str,
                t_id: str,
                log_path: str,
                timeout: int = 3600,
            ):
                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(), timeout=timeout
                    )
                    if log_path:
                        with open(log_path, "wb") as lf:
                            if stdout:
                                lf.write(stdout)
                            if stderr:
                                lf.write(b"\n--- STDERR ---\n")
                                lf.write(stderr)
                    if proc.returncode == 0:
                        logger.info("Beagle完成: workspace=%s task=%s", ws_id, t_id)
                    else:
                        logger.error(
                            "Beagle退出码=%s: workspace=%s task=%s",
                            proc.returncode,
                            ws_id,
                            t_id,
                        )
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    logger.error("Beagle超时(%ss): workspace=%s task=%s", timeout, ws_id, t_id)

            asyncio.create_task(
                _monitor_beagle(process, workspace_id, task_id, log_file)
            )

            return {
                "status": "running",
                "task_id": task_id,
                "workspace_id": workspace_id,
                "input_file": actual_input_file,
                "file_type": "vcf",
                "ref_panel": os.path.basename(ref_panel_path),
                "nthreads": min(nthreads, 2),
                "beagle_jar": beagle_jar,
                "process_pid": process.pid,
                "message": "填充任务已提交后台运行。可通过 get_workspace_status 查看是否完成。",
                "output_file": output_prefix + ".vcf.gz",
                "log_file": log_file,
            }
        except Exception as e:
            logger.error("启动Beagle失败: %s", e)

    return {
        "status": "error",
        "error": "基因型填充执行失败：Beagle未正确配置、参考面板不可用，或输入文件不符合要求。",
        "task_id": task_id,
        "workspace_id": workspace_id,
        "input_file": actual_input_file,
        "file_type": "vcf" if vcf_files else "plink",
        "ref_panel": ref_panel,
        "nthreads": nthreads,
        "diagnostics": {
            "refpanel_available": _refpanel_available,
            "ref_panel_file_available": ref_panel_available,
            "beagle_jar_found": beagle_jar is not None,
        },
    }


async def get_workspace_status(
    workspace_id: str = "",
) -> Dict[str, Any]:
    input_dir = f"{WORKSPACE_BASE}/{workspace_id}/input"
    output_dir = f"{WORKSPACE_BASE}/{workspace_id}/output"
    logs_dir = f"{WORKSPACE_BASE}/{workspace_id}/logs"

    input_files = os.listdir(input_dir) if os.path.exists(input_dir) else []
    output_files = os.listdir(output_dir) if os.path.exists(output_dir) else []
    log_files = os.listdir(logs_dir) if os.path.exists(logs_dir) else []

    status = "empty"
    if input_files:
        status = "data_uploaded"
    if output_files:
        status = "completed"

    latest_log_tail = ""
    if log_files:
        latest_log = sorted(log_files)[-1]
        log_path = os.path.join(logs_dir, latest_log)
        try:
            with open(log_path, "r", errors="replace") as f:
                latest_log_tail = "".join(f.readlines()[-20:])
            if "OutOfMemoryError" in latest_log_tail or "Exception" in latest_log_tail:
                status = "failed"
        except Exception:
            pass

    return {
        "workspace_id": workspace_id,
        "status": status,
        "input_files": input_files,
        "output_files": output_files,
        "log_files": log_files,
        "input_count": len(input_files),
        "output_count": len(output_files),
        "latest_log_tail": latest_log_tail,
    }
