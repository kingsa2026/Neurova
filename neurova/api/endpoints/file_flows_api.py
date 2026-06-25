"""
文件流转系统 API

提供以下端点:
- POST   /v1/file-flows                    创建文件流转模板
- GET    /v1/file-flows                    列出文件流转模板
- GET    /v1/file-flows/{flow_id}          获取模板详情
- POST   /v1/file-flows/{flow_id}/files    上传文件到流转
- GET    /v1/file-flows/{flow_id}/files    列出项目文件
- GET    /v1/file-flows/files/{file_id}    获取文件详情
- GET    /v1/file-flows/files/{file_id}/download  下载文件
- POST   /v1/file-flows/files/{file_id}/move      移动文件到指定阶段
- POST   /v1/file-flows/files/{file_id}/approve    审批通过文件
- POST   /v1/file-flows/files/{file_id}/reject     拒绝文件
- POST   /v1/file-flows/files/{file_id}/versions   创建文件新版本
- GET    /v1/file-flows/files/{file_id}/versions   列出文件版本
- GET    /v1/file-flows/stats              获取文件统计
"""

from neurova.core.logger import get_logger
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class FlowInfo(BaseModel):
    """文件流转模板信息"""

    flow_id: str
    name: str
    description: str = ""
    stages: List[str] = []
    project_id: Optional[str] = None
    created_at: float = 0
    updated_at: float = 0


class FlowCreate(BaseModel):
    """创建文件流转模板请求"""

    name: str = Field(..., description="模板名称")
    description: str = Field(default="", description="模板描述")
    stages: List[str] = Field(default=["upload", "review", "approved", "archived"], description="阶段列表")
    project_id: Optional[str] = Field(default=None, description="项目ID")


class FileInfo(BaseModel):
    """文件信息"""

    file_id: str
    filename: str
    flow_id: str
    stage: str = "upload"
    status: str = "pending"
    version: str = "1.0.0"
    size: int = 0
    mime_type: str = ""
    uploader_id: str = ""
    created_at: float = 0
    updated_at: float = 0


class FileVersion(BaseModel):
    """文件版本"""

    version_id: str
    file_id: str
    version: str
    size: int = 0
    created_at: float = 0


class FlowStats(BaseModel):
    """文件流转统计"""

    flow_id: str
    total_files: int = 0
    by_stage: Dict[str, int] = {}
    by_status: Dict[str, int] = {}


# ---------------------------------------------------------------------------
# In-Memory Store
# ---------------------------------------------------------------------------

_flows_store: Dict[str, Dict[str, Any]] = {}
_files_store: Dict[str, Dict[str, Any]] = {}
_versions_store: Dict[str, List[Dict[str, Any]]] = {}


def _get_ffs():
    """获取文件流转系统"""
    try:
        from neurova.projects.file_flow import FileFlowSystem

        return FileFlowSystem()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Routes - Flow Templates
# ---------------------------------------------------------------------------


@router.post("", response_model=FlowInfo)
async def create_flow(body: FlowCreate):
    """创建文件流转模板"""
    flow_id = str(uuid.uuid4())
    now = time.time()

    flow = {
        "flow_id": flow_id,
        "name": body.name,
        "description": body.description,
        "stages": body.stages,
        "project_id": body.project_id,
        "created_at": now,
        "updated_at": now,
    }
    _flows_store[flow_id] = flow
    return FlowInfo(**flow)


@router.get("", response_model=List[FlowInfo])
async def list_flows(
    project_id: Optional[str] = Query(default=None),
):
    """列出项目文件流转模板"""
    flows = list(_flows_store.values())
    if project_id:
        flows = [f for f in flows if f.get("project_id") == project_id]
    return [FlowInfo(**f) for f in flows]


@router.get("/{flow_id}", response_model=FlowInfo)
async def get_flow(flow_id: str):
    """获取模板详情"""
    flow = _flows_store.get(flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail=f"Flow '{flow_id}' not found")
    return FlowInfo(**flow)


# ---------------------------------------------------------------------------
# Routes - File Operations
# ---------------------------------------------------------------------------


@router.post("/{flow_id}/files", response_model=FileInfo)
async def upload_file(
    flow_id: str,
    file: UploadFile = File(...),
):
    """上传文件到流转"""
    flow = _flows_store.get(flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail=f"Flow '{flow_id}' not found")

    file_id = str(uuid.uuid4())
    now = time.time()

    # 存储文件
    storage_dir = Path("storage/file_flows") / flow_id
    storage_dir.mkdir(parents=True, exist_ok=True)

    file_path = storage_dir / f"{file_id}_{file.filename}"
    content = await file.read()
    file_path.write_bytes(content)

    mime, _ = mimetypes.guess_type(file.filename or "")

    file_info = {
        "file_id": file_id,
        "filename": file.filename,
        "flow_id": flow_id,
        "stage": flow.get("stages", ["upload"])[0],
        "status": "pending",
        "version": "1.0.0",
        "size": len(content),
        "mime_type": mime or "application/octet-stream",
        "uploader_id": "default",
        "path": str(file_path),
        "created_at": now,
        "updated_at": now,
    }
    _files_store[file_id] = file_info

    # 初始化版本历史
    _versions_store[file_id] = [
        {
            "version_id": str(uuid.uuid4()),
            "file_id": file_id,
            "version": "1.0.0",
            "size": len(content),
            "created_at": now,
        }
    ]

    return FileInfo(**file_info)


@router.get("/{flow_id}/files", response_model=List[FileInfo])
async def list_files(
    flow_id: str,
    stage: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
):
    """列出项目文件"""
    files = [f for f in _files_store.values() if f.get("flow_id") == flow_id]
    if stage:
        files = [f for f in files if f.get("stage") == stage]
    if status:
        files = [f for f in files if f.get("status") == status]
    return [FileInfo(**f) for f in files]


@router.get("/files/{file_id}", response_model=FileInfo)
async def get_file(file_id: str):
    """获取文件详情"""
    file_info = _files_store.get(file_id)
    if not file_info:
        raise HTTPException(status_code=404, detail=f"File '{file_id}' not found")
    return FileInfo(**file_info)


@router.get("/files/{file_id}/download")
async def download_file(file_id: str):
    """下载文件"""
    file_info = _files_store.get(file_id)
    if not file_info:
        raise HTTPException(status_code=404, detail=f"File '{file_id}' not found")

    file_path = Path(file_info.get("path", ""))
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")

    return FileResponse(
        str(file_path),
        media_type=file_info.get("mime_type", "application/octet-stream"),
        filename=file_info.get("filename", "download"),
    )


@router.post("/files/{file_id}/move", response_model=FileInfo)
async def move_to_stage(
    file_id: str,
    stage: str = Query(..., description="目标阶段"),
):
    """移动文件到指定阶段"""
    file_info = _files_store.get(file_id)
    if not file_info:
        raise HTTPException(status_code=404, detail=f"File '{file_id}' not found")

    flow = _flows_store.get(file_info.get("flow_id"))
    if flow and stage not in flow.get("stages", []):
        raise HTTPException(status_code=400, detail=f"Invalid stage '{stage}' for this flow")

    file_info["stage"] = stage
    file_info["updated_at"] = time.time()
    return FileInfo(**file_info)


@router.post("/files/{file_id}/approve", response_model=FileInfo)
async def approve_file(file_id: str):
    """审批通过文件"""
    file_info = _files_store.get(file_id)
    if not file_info:
        raise HTTPException(status_code=404, detail=f"File '{file_id}' not found")

    file_info["status"] = "approved"
    file_info["updated_at"] = time.time()
    return FileInfo(**file_info)


@router.post("/files/{file_id}/reject", response_model=FileInfo)
async def reject_file(file_id: str):
    """拒绝文件"""
    file_info = _files_store.get(file_id)
    if not file_info:
        raise HTTPException(status_code=404, detail=f"File '{file_id}' not found")

    file_info["status"] = "rejected"
    file_info["updated_at"] = time.time()
    return FileInfo(**file_info)


# ---------------------------------------------------------------------------
# Routes - Version Management
# ---------------------------------------------------------------------------


@router.post("/files/{file_id}/versions", response_model=FileVersion)
async def create_version(
    file_id: str,
    file: UploadFile = File(...),
):
    """创建文件新版本"""
    file_info = _files_store.get(file_id)
    if not file_info:
        raise HTTPException(status_code=404, detail=f"File '{file_id}' not found")

    # 获取当前版本号
    versions = _versions_store.get(file_id, [])
    current_version = file_info.get("version", "1.0.0")

    # 递增版本号
    parts = current_version.split(".")
    new_version = f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"

    # 存储新版本文件
    storage_dir = Path("storage/file_flows") / file_info.get("flow_id", "")
    storage_dir.mkdir(parents=True, exist_ok=True)

    version_path = storage_dir / f"{file_id}_v{new_version}_{file.filename}"
    content = await file.read()
    version_path.write_bytes(content)

    # 更新文件信息
    file_info["version"] = new_version
    file_info["size"] = len(content)
    file_info["updated_at"] = time.time()

    # 记录版本
    version_info = {
        "version_id": str(uuid.uuid4()),
        "file_id": file_id,
        "version": new_version,
        "size": len(content),
        "created_at": time.time(),
    }
    versions.append(version_info)
    _versions_store[file_id] = versions

    return FileVersion(**version_info)


@router.get("/files/{file_id}/versions", response_model=List[FileVersion])
async def list_versions(file_id: str):
    """列出文件版本"""
    if file_id not in _files_store:
        raise HTTPException(status_code=404, detail=f"File '{file_id}' not found")

    versions = _versions_store.get(file_id, [])
    return [FileVersion(**v) for v in versions]


# ---------------------------------------------------------------------------
# Routes - Statistics
# ---------------------------------------------------------------------------


@router.get("/stats", response_model=FlowStats)
async def get_stats(flow_id: str = Query(..., description="流转模板ID")):
    """获取文件统计"""
    if flow_id not in _flows_store:
        raise HTTPException(status_code=404, detail=f"Flow '{flow_id}' not found")

    files = [f for f in _files_store.values() if f.get("flow_id") == flow_id]

    by_stage: Dict[str, int] = {}
    by_status: Dict[str, int] = {}

    for f in files:
        stage = f.get("stage", "unknown")
        status = f.get("status", "unknown")
        by_stage[stage] = by_stage.get(stage, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1

    return FlowStats(
        flow_id=flow_id,
        total_files=len(files),
        by_stage=by_stage,
        by_status=by_status,
    )
