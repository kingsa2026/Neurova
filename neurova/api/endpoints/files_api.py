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

# ---------------------------------------------------------------------------
# SQLite 持久化（2026-09-08 产物预览计划 W1-4）：_files_store 原为纯内存，
# 重启即失 → 预览/附件 404。写穿 + 启动水合；坏库/磁盘丢文件静默降级
# （不阻塞启动，元数据丢失可接受——上传件本体在 storage/ 仍有目录可扫）。
# ---------------------------------------------------------------------------

_FILES_DB_PATH = "data/users.db"

_FILES_DDL = """
CREATE TABLE IF NOT EXISTS files (
    file_id TEXT PRIMARY KEY,
    filename TEXT, file_type TEXT, mime_type TEXT,
    size INTEGER, version TEXT, status TEXT,
    user_id TEXT, agent_id TEXT, path TEXT,
    created_at REAL, updated_at REAL
)
"""


def _files_db_path(db_path: Optional[str] = None) -> str:
    return db_path or _FILES_DB_PATH


def persist_file(file_id: str, info: Dict[str, Any], db_path: Optional[str] = None) -> None:
    """写穿单条文件元数据到 files 表（失败仅告警，不影响主流程）。"""
    try:
        Path(_files_db_path(db_path)).parent.mkdir(parents=True, exist_ok=True)
        import sqlite3

        conn = sqlite3.connect(_files_db_path(db_path))
        try:
            conn.execute(_FILES_DDL)
            conn.execute(
                "INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    info.get("file_id", file_id),
                    info.get("filename", ""),
                    info.get("file_type", "file"),
                    info.get("mime_type", ""),
                    info.get("size", 0),
                    info.get("version", "1.0.0"),
                    info.get("status", "active"),
                    info.get("user_id", ""),
                    info.get("agent_id", ""),
                    info.get("path", ""),
                    info.get("created_at", 0),
                    info.get("updated_at", 0),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 - 持久化失败降级为内存态
        logger.warning("files 元数据写穿失败（降级内存态）: %s", e)


def delete_file_record(file_id: str, db_path: Optional[str] = None) -> None:
    """从 files 表删除单条元数据（失败仅告警）。"""
    try:
        import sqlite3

        conn = sqlite3.connect(_files_db_path(db_path))
        try:
            conn.execute("DELETE FROM files WHERE file_id = ?", (file_id,))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("files 元数据删除失败: %s", e)


def hydrate_files_store(db_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """启动水合：磁盘文件仍在的行恢复进 _files_store，丢盘行自动清理。

    返回本次水合加载的记录（测试断言用）；坏库静默返回空（不阻塞启动）。
    """
    loaded: Dict[str, Dict[str, Any]] = {}
    db = _files_db_path(db_path)
    if not Path(db).exists():
        return loaded
    try:
        import sqlite3

        conn = sqlite3.connect(db)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM files").fetchall()
            for row in rows:
                rec = dict(row)
                # 磁盘文件已丢的行：清理元数据（防 404 僵尸）
                if rec.get("path") and not Path(rec["path"]).exists():
                    conn.execute("DELETE FROM files WHERE file_id = ?", (rec.get("file_id"),))
                    continue
                loaded[rec["file_id"]] = rec
                _files_store[rec["file_id"]] = rec
            conn.commit()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 - 坏库不阻塞启动
        logger.warning("files 元数据水合失败（空库降级）: %s", e)
        return {}
    logger.info("files 元数据水合完成: %d 条", len(loaded))
    return loaded

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
    persist_file(file_id, info)
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
    persist_file(file_id, info)
    return FileInfo(**info)


@router.delete("/{file_id}")
async def delete_file(
    file_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """删除文件"""
    info = _get_owned_file(file_id, current_user)
    del _files_store[file_id]
    delete_file_record(file_id)
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
