"""
文件管理 API

提供三层隔离存储的文件 CRUD:
- POST   /v1/files/upload        上传文件
- GET    /v1/files               列出文件
- GET    /v1/files/{file_id}     获取文件信息
- GET    /v1/files/{file_id}/preview  预览文件
- GET    /v1/files/{file_id}/download 下载文件
- PUT    /v1/files/{file_id}     更新文件信息
- DELETE /v1/files/{file_id}     删除文件
- GET    /v1/files/{file_id}/versions  获取版本历史
- POST   /v1/files/{file_id}/approve  批准文件
- POST   /v1/files/{file_id}/reject   拒绝文件
- GET    /v1/files/storage/info  获取存储使用情况
"""

import logging
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

STORAGE_ROOT = Path("storage/users")


class FileInfo(BaseModel):
    file_id: str
    filename: str
    file_type: str = "file"
    mime_type: str = ""
    size: int = 0
    version: str = "1.0.0"
    status: str = "active"
    user_id: str = ""
    agent_id: str = ""
    path: str = ""
    created_at: float = 0
    updated_at: float = 0


class FileUpdateRequest(BaseModel):
    filename: Optional[str] = None
    status: Optional[str] = None


class StorageInfo(BaseModel):
    user_id: str
    total_files: int = 0
    total_size: int = 0
    by_type: Dict[str, int] = {}


_files_store: Dict[str, Dict[str, Any]] = {}


def _determine_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"):
        return "image"
    if ext in (".mp3", ".wav", ".ogg", ".flac", ".aac"):
        return "audio"
    if ext in (".mp4", ".avi", ".mov", ".webm", ".mkv"):
        return "video"
    if ext in (".py", ".js", ".ts", ".java", ".cpp", ".go", ".rs"):
        return "code"
    if ext in (".md", ".txt", ".rst"):
        return "text"
    return "file"


@router.post("/upload", response_model=FileInfo)
async def upload_file(
    file: UploadFile = File(...),
    user_id: str = Query(default="default"),
    agent_id: str = Query(default="default"),
    session_id: str = Query(default="default"),
):
    """上传文件"""
    file_id = str(uuid.uuid4())
    now = time.time()

    # 确定存储路径
    file_type = _determine_file_type(file.filename or "unknown")
    storage_dir = STORAGE_ROOT / user_id / "agents" / agent_id / "sessions" / session_id / file_type
    storage_dir.mkdir(parents=True, exist_ok=True)

    file_path = storage_dir / f"{file_id}_{file.filename}"
    content = await file.read()
    file_path.write_bytes(content)

    mime, _ = mimetypes.guess_type(file.filename or "")
    info = {
        "file_id": file_id,
        "filename": file.filename,
        "file_type": file_type,
        "mime_type": mime or "application/octet-stream",
        "size": len(content),
        "version": "1.0.0",
        "status": "active",
        "user_id": user_id,
        "agent_id": agent_id,
        "path": str(file_path),
        "created_at": now,
        "updated_at": now,
    }
    _files_store[file_id] = info
    return FileInfo(**info)


@router.get("", response_model=List[FileInfo])
async def list_files(
    user_id: str = Query(default="default"),
    file_type: Optional[str] = Query(default=None),
):
    """列出文件"""
    files = [f for f in _files_store.values() if f.get("user_id") == user_id]
    if file_type:
        files = [f for f in files if f.get("file_type") == file_type]
    return [FileInfo(**f) for f in files]


@router.get("/storage/info", response_model=StorageInfo)
async def get_storage_info(user_id: str = Query(default="default")):
    """获取存储使用情况"""
    files = [f for f in _files_store.values() if f.get("user_id") == user_id]
    by_type: Dict[str, int] = {}
    for f in files:
        ft = f.get("file_type", "file")
        by_type[ft] = by_type.get(ft, 0) + 1
    return StorageInfo(
        user_id=user_id,
        total_files=len(files),
        total_size=sum(f.get("size", 0) for f in files),
        by_type=by_type,
    )


@router.get("/{file_id}", response_model=FileInfo)
async def get_file_info(file_id: str):
    """获取文件信息"""
    info = _files_store.get(file_id)
    if not info:
        raise HTTPException(status_code=404, detail="File not found")
    return FileInfo(**info)


@router.get("/{file_id}/preview")
async def preview_file(file_id: str):
    """预览文件"""
    info = _files_store.get(file_id)
    if not info:
        raise HTTPException(status_code=404, detail="File not found")
    file_path = Path(info["path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(str(file_path), media_type=info.get("mime_type", "application/octet-stream"))


@router.get("/{file_id}/download")
async def download_file(file_id: str):
    """下载文件"""
    info = _files_store.get(file_id)
    if not info:
        raise HTTPException(status_code=404, detail="File not found")
    file_path = Path(info["path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(
        str(file_path),
        media_type=info.get("mime_type", "application/octet-stream"),
        filename=info.get("filename", "download"),
    )


@router.put("/{file_id}", response_model=FileInfo)
async def update_file(file_id: str, body: FileUpdateRequest):
    """更新文件信息"""
    info = _files_store.get(file_id)
    if not info:
        raise HTTPException(status_code=404, detail="File not found")
    if body.filename is not None:
        info["filename"] = body.filename
    if body.status is not None:
        info["status"] = body.status
    info["updated_at"] = time.time()
    return FileInfo(**info)


@router.delete("/{file_id}")
async def delete_file(file_id: str):
    """删除文件"""
    info = _files_store.pop(file_id, None)
    if not info:
        raise HTTPException(status_code=404, detail="File not found")
    try:
        Path(info["path"]).unlink(missing_ok=True)
    except Exception:
        pass
    return {"code": 0, "message": "File deleted"}


@router.get("/{file_id}/versions")
async def get_file_versions(file_id: str):
    """获取版本历史"""
    info = _files_store.get(file_id)
    if not info:
        raise HTTPException(status_code=404, detail="File not found")
    return {
        "code": 0,
        "data": {"versions": [{"version": info.get("version", "1.0.0"), "created_at": info.get("created_at", 0)}]},
    }


@router.post("/{file_id}/approve")
async def approve_file(file_id: str):
    """批准文件"""
    info = _files_store.get(file_id)
    if not info:
        raise HTTPException(status_code=404, detail="File not found")
    info["status"] = "approved"
    info["updated_at"] = time.time()
    return {"code": 0, "message": "File approved"}


@router.post("/{file_id}/reject")
async def reject_file(file_id: str):
    """拒绝文件"""
    info = _files_store.get(file_id)
    if not info:
        raise HTTPException(status_code=404, detail="File not found")
    info["status"] = "rejected"
    info["updated_at"] = time.time()
    return {"code": 0, "message": "File rejected"}
