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

from neurova.core.logger import get_logger
import mimetypes
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from neurova.api.auth import get_current_user

logger = get_logger(__name__)
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

# P0 安全修复: 路径段只允许字母数字与 . _ -，禁止 .. / \ 等穿越字符
_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _validate_path_segment(value: str, name: str) -> str:
    """校验路径段参数，非法时抛 400（防路径穿越）"""
    if not value or ".." in value or "/" in value or "\\" in value or not _PATH_SEGMENT_RE.match(value):
        raise HTTPException(status_code=400, detail=f"Invalid {name}")
    return value


def _get_owned_file(file_id: str, current_user: Dict[str, Any]) -> Dict[str, Any]:
    """按 file_id 获取文件，非属主与不存在统一返回 404（防 IDOR 探测）"""
    info = _files_store.get(file_id)
    if not info or info.get("user_id") != current_user["user_id"]:
        raise HTTPException(status_code=404, detail="File not found")
    return info


def _determine_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tiff", ".tif"):
        return "image"
    if ext in (".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a", ".wma"):
        return "audio"
    if ext in (".mp4", ".avi", ".mov", ".webm", ".mkv", ".flv", ".m4v"):
        return "video"
    if ext in (".py", ".js", ".ts", ".java", ".cpp", ".go", ".rs", ".vue", ".css", ".json", ".xml"):
        return "code"
    if ext in (".md", ".txt", ".rst"):
        return "text"
    # R-3 修复: Office/PDF/HTML 归为 document（此前全落 "file"，
    # 会话路由无法按类型分派附件处理）
    if ext in (
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".csv",
        ".html",
        ".htm",
    ):
        return "document"
    return "file"


def get_attachment_info(file_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """按 file_id 读取文件元数据（同用户限定，防 IDOR）。

    供会话路由附件注入使用（console/chat 的 file_ids 解析）。
    非属主或不存在返回 None（与 _get_owned_file 的 404 语义一致）。
    """
    info = _files_store.get(file_id)
    if not info or info.get("user_id") != user_id:
        return None
    return dict(info)


def get_attachment_bytes(file_id: str) -> Optional[bytes]:
    """按 file_id 从磁盘读取文件内容；文件不存在返回 None。

    R-3 加固: info["path"] 是相对路径（相对进程 CWD），但守护进程 CWD
    可能与项目根不一致。依次尝试：原始路径 → STORAGE_ROOT 相对 → 项目根。
    """
    info = _files_store.get(file_id)
    if not info:
        return None
    raw_path = str(info.get("path") or "")
    if not raw_path:
        return None

    candidates: List[Path] = []
    p = Path(raw_path)
    candidates.append(p)
    if not p.is_absolute():
        # 相对 STORAGE_ROOT（storage/users）——上传时路径带 storage/users 前缀，
        # 因此相对于 CWD 与项目根均可
        candidates.append(Path(".") / raw_path)
        # STORAGE_ROOT 的父级（项目根）相对解析
        candidates.append(Path(__file__).resolve().parents[3] / raw_path)

    for cand in candidates:
        try:
            if cand.exists():
                return cand.read_bytes()
        except Exception:
            continue
    return None


@router.post("/upload", response_model=FileInfo)
async def upload_file(
    file: UploadFile = File(...),
    agent_id: str = Query(default="default"),
    session_id: str = Query(default="default"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """上传文件"""
    file_id = str(uuid.uuid4())
    now = time.time()
    user_id = current_user["user_id"]

    # P0 安全修复: agent_id/session_id 参与存储路径拼接，必须先净化防路径穿越
    _validate_path_segment(agent_id, "agent_id")
    _validate_path_segment(session_id, "session_id")

    # 净化文件名：只取 basename，防止路径遍历（../../etc/passwd 等）
    raw_filename = file.filename or "unknown"
    safe_filename = Path(raw_filename).name
    if not safe_filename or safe_filename in (".", ".."):
        safe_filename = "unknown"

    # 确定存储路径
    file_type = _determine_file_type(safe_filename)
    storage_dir = STORAGE_ROOT / user_id / "agents" / agent_id / "sessions" / session_id / file_type
    # 根因防御: 净化后仍校验最终目录必须位于用户存储根内
    try:
        storage_dir.resolve().relative_to((STORAGE_ROOT / user_id).resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path segment")
    storage_dir.mkdir(parents=True, exist_ok=True)

    file_path = storage_dir / f"{file_id}_{safe_filename}"
    # 二次验证：最终路径必须在 storage_dir 内（防御性编程）
    try:
        file_path.resolve().relative_to(storage_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")

    content = await file.read()
    file_path.write_bytes(content)

    mime, _ = mimetypes.guess_type(safe_filename)
    info = {
        "file_id": file_id,
        "filename": safe_filename,
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
    file_type: Optional[str] = Query(default=None),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """列出文件"""
    user_id = current_user["user_id"]
    files = [f for f in _files_store.values() if f.get("user_id") == user_id]
    if file_type:
        files = [f for f in files if f.get("file_type") == file_type]
    return [FileInfo(**f) for f in files]


@router.get("/storage/info", response_model=StorageInfo)
async def get_storage_info(current_user: Dict[str, Any] = Depends(get_current_user)):
    """获取存储使用情况"""
    user_id = current_user["user_id"]
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
async def get_file_info(
    file_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取文件信息"""
    info = _get_owned_file(file_id, current_user)
    return FileInfo(**info)


@router.get("/{file_id}/preview")
async def preview_file(
    file_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """预览文件"""
    info = _get_owned_file(file_id, current_user)
    file_path = Path(info["path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(str(file_path), media_type=info.get("mime_type", "application/octet-stream"))


@router.get("/{file_id}/download")
async def download_file(
    file_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """下载文件"""
    info = _get_owned_file(file_id, current_user)
    file_path = Path(info["path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(
        str(file_path),
        media_type=info.get("mime_type", "application/octet-stream"),
        filename=info.get("filename", "download"),
    )


@router.put("/{file_id}", response_model=FileInfo)
async def update_file(
    file_id: str,
    body: FileUpdateRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """更新文件信息"""
    info = _get_owned_file(file_id, current_user)
    if body.filename is not None:
        info["filename"] = body.filename
    if body.status is not None:
        info["status"] = body.status
    info["updated_at"] = time.time()
    return FileInfo(**info)


@router.delete("/{file_id}")
async def delete_file(
    file_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """删除文件"""
    info = _get_owned_file(file_id, current_user)
    del _files_store[file_id]
    try:
        Path(info["path"]).unlink(missing_ok=True)
    except Exception:
        pass
    return {"code": 0, "message": "File deleted"}


@router.get("/{file_id}/versions")
async def get_file_versions(
    file_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取版本历史"""
    info = _get_owned_file(file_id, current_user)
    return {
        "code": 0,
        "data": {"versions": [{"version": info.get("version", "1.0.0"), "created_at": info.get("created_at", 0)}]},
    }


@router.post("/{file_id}/approve")
async def approve_file(
    file_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """批准文件"""
    info = _get_owned_file(file_id, current_user)
    info["status"] = "approved"
    info["updated_at"] = time.time()
    return {"code": 0, "message": "File approved"}


@router.post("/{file_id}/reject")
async def reject_file(
    file_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """拒绝文件"""
    info = _get_owned_file(file_id, current_user)
    info["status"] = "rejected"
    info["updated_at"] = time.time()
    return {"code": 0, "message": "File rejected"}
