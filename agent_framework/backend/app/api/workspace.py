"""
工作区路由

提供工作区管理的RESTful API
"""

import os
import re
import shutil
import logging
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, status, UploadFile, File, Form, Request

from app.config import settings
from app.beagle_paths import default_ref_panel_vcf_path, resolve_beagle_jar, resolve_ref_panel_vcf
from app.workspace_session_store import (
    bind_session_workspace,
    get_workspace_for_session,
)

logger = logging.getLogger(__name__)

WORKSPACE_BASE = settings.workspace_base_path

_running_imputation_tasks: Dict[str, Dict[str, Any]] = {}


def _calculate_beagle_progress(log_content: str) -> int:
    """
    根据Beagle日志内容计算进度百分比

    Beagle日志特点：
    - 开始时显示 "Start time"
    - 窗口处理时显示 "Window X [range]"
    - 完成时显示 "End time" 和 "finished"
    - 最后一个窗口完成后立即显示 "finished"
    """
    if not log_content:
        return 0

    if "finished" in log_content.lower():
        return 100

    windows = []
    for line in log_content.split("\n"):
        if "Window" in line and "[" in line:
            try:
                m = re.search(r"Window\s+(\d+)\s+\[", line)
                if m:
                    windows.append(int(m.group(1)))
            except Exception:
                pass

    if not windows:
        if "Start time" in log_content:
            return 5
        return 0

    max_window = max(windows)
    estimated_total_windows = 30
    base_progress = min((max_window / estimated_total_windows) * 95, 95)
    return int(base_progress)

def _validate_workspace_id(workspace_id: str) -> str:
    if not re.match(r'^[a-zA-Z0-9_\-]+$', workspace_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的工作区ID: {workspace_id}",
        )
    real_base = os.path.realpath(WORKSPACE_BASE)
    real_path = os.path.realpath(os.path.join(WORKSPACE_BASE, workspace_id))
    if not real_path.startswith(real_base + os.sep):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="非法工作区路径",
        )
    return workspace_id

router = APIRouter()


class WorkspaceCreateRequest(BaseModel):
    description: Optional[str] = Field(None, description="工作区描述")
    workspace_type: str = Field("imputation", description="工作区类型")
    workspace_id: Optional[str] = Field(None, description="工作区ID（由MCP传入，为空则自动生成）")
    session_id: Optional[str] = Field(None, description="绑定的对话会话ID（一个对话对应一个工作区）")


class WorkspaceResponse(BaseModel):
    workspace_id: str = Field(..., description="工作区ID")
    workspace_type: str = Field(..., description="工作区类型")
    status: str = Field(..., description="状态")
    description: Optional[str] = Field(None, description="描述")
    directories: Dict[str, str] = Field(default_factory=dict, description="目录结构")
    files: Dict[str, List[str]] = Field(default_factory=dict, description="文件列表")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")


class WorkspaceListResponse(BaseModel):
    workspaces: List[WorkspaceResponse] = Field(default_factory=list)
    total: int = Field(0, description="总数")


class FileUploadResponse(BaseModel):
    success: bool = Field(True, description="是否成功")
    workspace_id: str = Field(..., description="工作区ID")
    filename: str = Field(..., description="文件名")
    file_size: int = Field(..., description="文件大小")
    file_path: str = Field(..., description="文件路径")
    message: str = Field(..., description="消息")


class WorkspaceQueryRequest(BaseModel):
    query_type: str = Field("gene", description="查询类型: gene/region/id")
    query_value: str = Field(..., description="查询内容")
    sample_filter: Optional[str] = Field("", description="可选品种筛选")
    sv_type: Optional[str] = Field("", description="可选SV类型: DEL/INS")
    limit: int = Field(20, ge=1, le=200, description="返回条数上限")


def _get_workspace_dirs(workspace_id: str) -> Dict[str, str]:
    return {
        "root": f"{WORKSPACE_BASE}/{workspace_id}",
        "input": f"{WORKSPACE_BASE}/{workspace_id}/input",
        "output": f"{WORKSPACE_BASE}/{workspace_id}/output",
        "logs": f"{WORKSPACE_BASE}/{workspace_id}/logs",
    }


def _ensure_dirs(workspace_id: str) -> Dict[str, str]:
    dirs = _get_workspace_dirs(workspace_id)
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    return dirs


def _list_dir_files(path: str) -> List[str]:
    if not os.path.exists(path):
        return []
    return [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]


@router.post(
    "/workspaces",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建工作区",
)
async def create_workspace(request: WorkspaceCreateRequest, http_request: Request) -> WorkspaceResponse:
    try:
        if request.session_id:
            existing = get_workspace_for_session(request.session_id)
            if existing:
                workspace_id = existing["workspace_id"]
                workspace_type = existing.get("workspace_type") or request.workspace_type
                dirs = _ensure_dirs(workspace_id)
                try:
                    ws_manager = http_request.app.state.ws_manager
                    asyncio.create_task(ws_manager.send_to_session(request.session_id, {
                        "type": "workspace_activate",
                        "payload": {
                            "session_id": request.session_id,
                            "workspace_id": workspace_id,
                            "workspace_type": workspace_type,
                            "description": request.description,
                            "reused": True,
                        },
                    }))
                except Exception as e:
                    logger.warning(f"推送workspace_activate事件失败: {e}")
                return WorkspaceResponse(
                    workspace_id=workspace_id,
                    workspace_type=workspace_type,
                    status="existing",
                    description=request.description,
                    directories=dirs,
                    files={
                        "input": _list_dir_files(dirs["input"]),
                        "output": _list_dir_files(dirs["output"]),
                        "logs": _list_dir_files(dirs["logs"]),
                    },
                    created_at=existing.get("updated_at", datetime.utcnow().isoformat()),
                    updated_at=datetime.utcnow().isoformat(),
                )

        workspace_id = request.workspace_id or f"ws_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        _validate_workspace_id(workspace_id)
        dirs = _ensure_dirs(workspace_id)

        if request.session_id:
            bind_session_workspace(request.session_id, workspace_id, request.workspace_type)

        try:
            ws_manager = http_request.app.state.ws_manager
            if request.session_id:
                asyncio.create_task(ws_manager.send_to_session(request.session_id, {
                    "type": "workspace_activate",
                    "payload": {
                        "session_id": request.session_id,
                        "workspace_id": workspace_id,
                        "workspace_type": request.workspace_type,
                        "description": request.description,
                    },
                }))
        except Exception as e:
            logger.warning(f"推送workspace_activate事件失败: {e}")

        return WorkspaceResponse(
            workspace_id=workspace_id,
            workspace_type=request.workspace_type,
            status="created",
            description=request.description,
            directories=dirs,
            files={"input": [], "output": [], "logs": []},
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建工作区失败: {str(e)}",
        )


@router.get(
    "/workspaces",
    response_model=WorkspaceListResponse,
    summary="列出工作区",
)
async def list_workspaces(
    limit: int = 20,
    offset: int = 0,
    workspace_type: Optional[str] = None,
) -> WorkspaceListResponse:
    workspaces = []
    if os.path.exists(WORKSPACE_BASE):
        for name in sorted(os.listdir(WORKSPACE_BASE)):
            if name.startswith("ws_"):
                root = os.path.join(WORKSPACE_BASE, name)
                if os.path.isdir(root):
                    workspaces.append(
                        WorkspaceResponse(
                            workspace_id=name,
                            workspace_type="imputation",
                            status="active",
                            directories=_get_workspace_dirs(name),
                            files={
                                "input": _list_dir_files(f"{root}/input"),
                                "output": _list_dir_files(f"{root}/output"),
                                "logs": _list_dir_files(f"{root}/logs"),
                            },
                            created_at=datetime.utcnow().isoformat(),
                            updated_at=datetime.utcnow().isoformat(),
                        )
                    )

    return WorkspaceListResponse(
        workspaces=workspaces[offset : offset + limit],
        total=len(workspaces),
    )


@router.get(
    "/workspaces/by-session/{session_id}",
    summary="按对话会话获取绑定的工作区",
)
async def get_workspace_by_session(session_id: str) -> Dict[str, Any]:
    entry = get_workspace_for_session(session_id)
    if not entry:
        return {"session_id": session_id, "workspace_id": None}
    workspace_id = entry["workspace_id"]
    root = f"{WORKSPACE_BASE}/{workspace_id}"
    if not os.path.exists(root):
        return {"session_id": session_id, "workspace_id": None}
    return {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "workspace_type": entry.get("workspace_type", "imputation"),
        "updated_at": entry.get("updated_at"),
        "files": {
            "input": _list_dir_files(f"{root}/input"),
            "output": _list_dir_files(f"{root}/output"),
            "logs": _list_dir_files(f"{root}/logs"),
        },
    }


@router.get(
    "/workspaces/{workspace_id}",
    response_model=WorkspaceResponse,
    summary="获取工作区",
)
async def get_workspace(workspace_id: str) -> WorkspaceResponse:
    _validate_workspace_id(workspace_id)
    root = f"{WORKSPACE_BASE}/{workspace_id}"
    if not os.path.exists(root):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"工作区不存在: {workspace_id}",
        )

    return WorkspaceResponse(
        workspace_id=workspace_id,
        workspace_type="imputation",
        status="active",
        directories=_get_workspace_dirs(workspace_id),
        files={
            "input": _list_dir_files(f"{root}/input"),
            "output": _list_dir_files(f"{root}/output"),
            "logs": _list_dir_files(f"{root}/logs"),
        },
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
    )


@router.delete(
    "/workspaces/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除工作区",
)
async def delete_workspace(workspace_id: str):
    _validate_workspace_id(workspace_id)
    root = f"{WORKSPACE_BASE}/{workspace_id}"
    if os.path.exists(root):
        shutil.rmtree(root)
    return None


@router.post(
    "/workspaces/{workspace_id}/upload",
    response_model=FileUploadResponse,
    summary="上传文件到工作区",
)
async def upload_file(
    workspace_id: str,
    file: UploadFile = File(..., description="要上传的文件"),
    description: Optional[str] = Form(None, description="文件描述"),
) -> FileUploadResponse:
    _validate_workspace_id(workspace_id)
    try:
        _ensure_dirs(workspace_id)
        input_dir = f"{WORKSPACE_BASE}/{workspace_id}/input"

        filename = os.path.basename(file.filename or "unknown")
        file_path = os.path.join(input_dir, filename)
        real_input_dir = os.path.realpath(input_dir)
        real_file_path = os.path.realpath(file_path)
        if not real_file_path.startswith(real_input_dir + os.sep) and real_file_path != real_input_dir:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="非法文件名",
            )

        # 流式落盘 + 增量大小校验：边读边写，超限立即中断并删除，
        # 避免把整个上传体读入内存（防 2GB 上传内存 DoS）。
        max_bytes = settings.workspace_max_upload_mb * 1024 * 1024
        chunk_size = 1024 * 1024
        file_size = 0
        with open(file_path, "wb") as f:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > max_bytes:
                    f.close()
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"文件大小不能超过 {settings.workspace_max_upload_mb}MB",
                    )
                f.write(chunk)

        logger.info(f"文件上传成功: {filename} -> {file_path} ({file_size} bytes)")

        asyncio.create_task(_notify_mcp_file_uploaded(workspace_id, filename, file_size))

        return FileUploadResponse(
            success=True,
            workspace_id=workspace_id,
            filename=filename,
            file_size=file_size,
            file_path=file_path,
            message="文件上传成功",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文件上传失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"上传文件失败: {str(e)}",
        )


@router.get(
    "/workspaces/{workspace_id}/files",
    summary="列出工作区文件",
)
async def list_files(workspace_id: str) -> Dict[str, Any]:
    _validate_workspace_id(workspace_id)
    root = f"{WORKSPACE_BASE}/{workspace_id}"
    if not os.path.exists(root):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"工作区不存在: {workspace_id}",
        )

    return {
        "workspace_id": workspace_id,
        "files": {
            "input": _list_dir_files(f"{root}/input"),
            "output": _list_dir_files(f"{root}/output"),
            "logs": _list_dir_files(f"{root}/logs"),
        },
    }


@router.post(
    "/workspaces/{workspace_id}/query",
    summary="工作区SV查询（直连真实数据）",
)
async def workspace_query(workspace_id: str, request: WorkspaceQueryRequest) -> Dict[str, Any]:
    _validate_workspace_id(workspace_id)

    query_type = str(request.query_type or "").strip().lower()
    if query_type == "sv_id":
        query_type = "id"
    if query_type not in {"gene", "region", "id"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的查询类型: {request.query_type}",
        )

    query_value = str(request.query_value or "").strip()
    if not query_value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="查询内容不能为空",
        )

    try:
        from app.tools.data import query_sv as query_sv_tool

        result = await query_sv_tool(
            query_type=query_type,
            query_value=query_value,
            sample_filter=str(request.sample_filter or ""),
            sv_type=str(request.sv_type or ""),
            limit=int(request.limit or 20),
        )
    except Exception as e:
        logger.error(f"工作区查询失败: workspace={workspace_id}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询执行失败: {str(e)}",
        )

    if result.get("status") != "success":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "查询失败"),
        )

    rows = []
    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "id": item.get("id"),
                "chr": item.get("chr"),
                "pos": item.get("start"),
                "end": item.get("end"),
                "type": item.get("type"),
                "gene": item.get("gene"),
                "mean_frequency": item.get("mean_frequency"),
                "top_breed_frequencies": item.get("top_breed_frequencies") or [],
                "breed_frequencies": item.get("breed_frequencies") or {},
                "domestication_summary": item.get("domestication_summary"),
            }
        )

    return {
        "success": True,
        "workspace_id": workspace_id,
        "query": {
            "type": query_type,
            "value": query_value,
            "sample_filter": str(request.sample_filter or ""),
            "sv_type": str(request.sv_type or ""),
        },
        "total": result.get("total", len(rows)),
        "has_more": result.get("has_more", False),
        "results": rows,
        "default_summary": result.get("default_summary"),
        "data_source": result.get("data_source", "真实CSV数据"),
    }


@router.post(
    "/workspaces/{workspace_id}/validate",
    summary="验证工作区文件",
)
async def validate_files(workspace_id: str) -> Dict[str, Any]:
    _validate_workspace_id(workspace_id)
    input_dir = f"{WORKSPACE_BASE}/{workspace_id}/input"
    files = _list_dir_files(input_dir)

    errors = []
    warnings = []

    for f in files:
        if not f.endswith((".vcf", ".vcf.gz", ".bed", ".bim", ".fam")):
            errors.append(f"不支持的文件格式: {f}")

    if not files:
        errors.append("输入目录中没有文件")

    plink_files = [f for f in files if f.endswith((".bed", ".bim", ".fam"))]
    if plink_files:
        has_bed = any(f.endswith(".bed") for f in plink_files)
        has_bim = any(f.endswith(".bim") for f in plink_files)
        has_fam = any(f.endswith(".fam") for f in plink_files)
        if not (has_bed and has_bim and has_fam):
            warnings.append("PLINK格式需要同时包含.bed, .bim, .fam三个文件")

    return {
        "success": len(errors) == 0,
        "workspace_id": workspace_id,
        "validation_result": {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        },
        "files": files,
    }


@router.post(
    "/workspaces/{workspace_id}/impute",
    summary="执行基因型填充",
)
async def run_imputation(
    workspace_id: str,
    ref_panel: str = Form("default", description="参考面板"),
    nthreads: int = Form(4, description="线程数"),
) -> Dict[str, Any]:
    _validate_workspace_id(workspace_id)
    input_dir = f"{WORKSPACE_BASE}/{workspace_id}/input"
    output_dir = f"{WORKSPACE_BASE}/{workspace_id}/output"
    logs_dir = f"{WORKSPACE_BASE}/{workspace_id}/logs"

    if not os.path.exists(input_dir):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"工作区不存在: {workspace_id}",
        )

    files = _list_dir_files(input_dir)
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="输入目录中没有文件，请先上传数据",
        )

    vcf_files = [f for f in files if f.endswith((".vcf", ".vcf.gz"))]
    plink_files = [f for f in files if f.endswith((".bed", ".bim", ".fam"))]

    if not vcf_files and not plink_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未找到有效的基因型数据文件(VCF或PLINK格式)",
        )

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)

    task_id = f"task_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    ref_panel_path = default_ref_panel_vcf_path()
    ref_panel_available = bool(resolve_ref_panel_vcf())

    beagle_jar = resolve_beagle_jar()

    if not beagle_jar or not ref_panel_available:
        return {
            "success": False,
            "workspace_id": workspace_id,
            "task_id": task_id,
            "status": "error",
            "error": "Beagle或参考面板不可用，无法执行填充",
            "diagnostics": {
                "beagle_jar_found": beagle_jar is not None,
                "ref_panel_available": ref_panel_available,
                "ref_panel_path": ref_panel_path,
            },
            "message": "填充执行失败：缺少Beagle jar或参考面板文件",
        }

    if vcf_files:
        input_file = vcf_files[0]
        input_path = os.path.join(input_dir, input_file)
    else:
        bed_file = next((f for f in plink_files if f.endswith(".bed")), None)
        input_file = bed_file.replace(".bed", "") if bed_file else ""
        input_path = os.path.join(input_dir, input_file)

    output_prefix = os.path.join(output_dir, f"imputed_{task_id}")
    log_file = os.path.join(logs_dir, f"beagle_{task_id}.log")

    # 并发上限：每个 Beagle 进程占用数 GB 内存，限制全局同时运行数量，防资源耗尽。
    # 同步检查 + 占位（中间无 await，单线程事件循环下原子），随后再启动子进程。
    existing_task = _running_imputation_tasks.get(workspace_id)
    if existing_task and existing_task.get("status") == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该工作区已有填充任务在运行，请等待其完成",
        )
    running_count = sum(
        1 for t in _running_imputation_tasks.values() if t.get("status") == "running"
    )
    if running_count >= settings.imputation_max_concurrent:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"填充任务繁忙：当前已有 {running_count} 个任务在运行"
                f"（上限 {settings.imputation_max_concurrent}），请稍后再试"
            ),
        )
    # 立即占位，防止并发请求在子进程启动前重复通过检查
    _running_imputation_tasks[workspace_id] = {
        "task_id": task_id,
        "pid": None,
        "start_time": datetime.utcnow().isoformat(),
        "status": "running",
        "log_file": log_file,
        "output_prefix": output_prefix,
        "output_file": output_prefix + ".vcf.gz",
    }

    cmd = [
        "java", "-Xmx4096m", "-jar", beagle_jar,
        "gt=" + input_path,
        "ref=" + ref_panel_path,
        "out=" + output_prefix,
        "nthreads=" + str(min(nthreads, 2)),
        "window=40",
        "overlap=5",
        "impute=true",
        "gp=true",
    ]

    logger.info(f"Beagle命令: {' '.join(cmd)}")

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:
        logger.error(f"启动Beagle进程失败: {e}")
        _running_imputation_tasks.pop(workspace_id, None)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"启动填充进程失败: {str(e)}",
        )

    async def _monitor_beagle(proc: asyncio.subprocess.Process):
        _running_imputation_tasks[workspace_id] = {
            "task_id": task_id,
            "pid": process.pid,
            "start_time": datetime.utcnow().isoformat(),
            "status": "running",
            "log_file": log_file,
            "output_prefix": output_prefix,
            "output_file": output_prefix + ".vcf.gz",
        }
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=7200)
            with open(log_file, "wb") as lf:
                if stdout:
                    lf.write(stdout)
                if stderr:
                    lf.write(b"\n--- STDERR ---\n")
                    lf.write(stderr)
            if proc.returncode == 0:
                logger.info(f"Beagle完成: workspace={workspace_id}")
                _running_imputation_tasks[workspace_id]["status"] = "completed"
            else:
                logger.error(f"Beagle退出码={proc.returncode}: workspace={workspace_id}")
                _running_imputation_tasks[workspace_id]["status"] = "failed"
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.error(f"Beagle超时已终止: workspace={workspace_id}")
            _running_imputation_tasks[workspace_id]["status"] = "timeout"

    asyncio.create_task(_monitor_beagle(process))

    return {
        "success": True,
        "workspace_id": workspace_id,
        "task_id": task_id,
        "status": "running",
        "input_file": input_file,
        "file_type": "vcf" if vcf_files else "plink",
        "ref_panel": os.path.basename(ref_panel_path),
        "nthreads": nthreads,
        "beagle_jar": beagle_jar,
        "process_pid": process.pid,
        "output_file": output_prefix + ".vcf.gz",
        "log_file": log_file,
        "message": "填充任务已启动，使用Beagle + 参考面板",
    }


@router.get(
    "/workspaces/{workspace_id}/status",
    summary="获取工作区状态",
)
async def get_workspace_status(workspace_id: str) -> Dict[str, Any]:
    _validate_workspace_id(workspace_id)
    root = f"{WORKSPACE_BASE}/{workspace_id}"
    if not os.path.exists(root):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"工作区不存在: {workspace_id}",
        )

    input_dir = f"{root}/input"
    output_dir = f"{root}/output"
    logs_dir = f"{root}/logs"

    input_files = _list_dir_files(input_dir)
    output_files = _list_dir_files(output_dir)
    log_files = _list_dir_files(logs_dir)

    running_task = _running_imputation_tasks.get(workspace_id)
    ws_status = "empty"
    progress = 0
    log_content = ""
    beagle_phase = ""
    beagle_markers = ""

    if running_task:
        ws_status = running_task["status"]
        log_file = running_task.get("log_file")
        if log_file and os.path.exists(log_file):
            try:
                with open(log_file, "r", errors="replace") as f:
                    log_content = f.read()
                lines = log_content.split("\n")
                for line in lines:
                    if "Window" in line or "window" in line:
                        beagle_phase = line.strip()
                    if "markers" in line.lower():
                        beagle_markers = line.strip()
                if ws_status == "running":
                    progress = _calculate_beagle_progress(log_content)
            except Exception:
                pass
    else:
        if output_files:
            ws_status = "completed"
            progress = 100
        elif input_files:
            ws_status = "data_uploaded"
            progress = 10

    if log_files and not running_task:
        latest_log = sorted(log_files)[-1]
        log_path = os.path.join(logs_dir, latest_log)
        try:
            with open(log_path, "r", errors="replace") as f:
                log_content = "".join(f.readlines()[-50:])
            if not output_files and (
                "OutOfMemoryError" in log_content
                or "Exception in thread" in log_content
                or "Beagle退出码=" in log_content
            ):
                ws_status = "failed"
        except Exception:
            pass

    return {
        "workspace_id": workspace_id,
        "status": ws_status,
        "input_files": input_files,
        "output_files": output_files,
        "log_files": log_files,
        "log_content": log_content,
        "input_count": len(input_files),
        "output_count": len(output_files),
        "beagle_phase": beagle_phase,
        "beagle_markers": beagle_markers,
        "task_info": running_task if running_task else None,
    }


@router.get(
    "/workspaces/{workspace_id}/download/{filename}",
    summary="下载工作区文件",
)
async def download_workspace_file(workspace_id: str, filename: str):
    _validate_workspace_id(workspace_id)
    _validate_workspace_id(filename.replace(".", "_"))

    root = os.path.realpath(f"{WORKSPACE_BASE}/{workspace_id}")
    if not os.path.exists(root):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"工作区不存在: {workspace_id}",
        )

    for subdir in ["output", "input", "logs"]:
        file_path = os.path.realpath(os.path.join(root, subdir, filename))
        if file_path.startswith(root + os.sep) and os.path.isfile(file_path):
            from fastapi.responses import FileResponse
            return FileResponse(
                path=file_path,
                filename=filename,
                media_type="application/octet-stream",
            )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"文件不存在: {filename}",
    )


async def _notify_mcp_file_uploaded(workspace_id: str, filename: str, file_size: int):
    """
    上传成功后通知MCP工作区有文件更新
    MCP会扫描真实文件系统更新其index
    """
    try:
        import requests
        resp = requests.post(
            f"{settings.mcp_server_url.rstrip('/')}/mcp/v1/imputation/sync-upload",
            json={
                "workspace_id": workspace_id,
                "filename": filename,
                "file_size": file_size,
            },
            timeout=5,
        )
        if resp.status_code == 200:
            logger.info(f"MCP已同步文件: {workspace_id}/{filename}")
        else:
            logger.warning(f"MCP同步失败: {resp.status_code}")
    except Exception as e:
        logger.warning(f"通知MCP失败（不影响主流程）: {e}")
