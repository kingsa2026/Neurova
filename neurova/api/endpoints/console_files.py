"""Console file endpoints; runtime state remains owned by console.

属主隔离（批 S1，specs/2026-10-31-full-repo-defect-sweep-fixplan.md）：
附件按上传者 user_id 分域落盘，list/download/delete 只在自己的域内活动——
修前共享目录全可见可删，任何登录用户可动他人附件。
"""
import re
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from neurova.api.deps import get_current_user

router = APIRouter()

_SAFE_USER_SEGMENT = re.compile(r"[^A-Za-z0-9_\-]")


def _user_scope(current_user: Dict[str, Any]):
    """当前用户的附件域目录（user_id 归一为安全路径段，空值落 anonymous 域）。"""
    from . import console as api

    user_id = str((current_user or {}).get("user_id") or "")
    safe_user = _SAFE_USER_SEGMENT.sub("_", user_id) or "anonymous"
    scope = api._CONSOLE_UPLOAD_DIR / safe_user
    scope.mkdir(parents=True, exist_ok=True)
    return scope


@router.post("/upload")
async def post_console_upload(
    request: Request,
    file: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """上传文件（BUG AUDIT S-08: 原零鉴权, 匿名可投递任意文件）"""
    from . import console as api
    scope = _user_scope(current_user)
    safe_name = api._safe_filename(file.filename or "unnamed")
    file_id = str(api.uuid.uuid4())[:8]
    dest = scope / f"{file_id}_{safe_name}"

    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 100MB)")
    dest.write_bytes(content)

    file_info = {
        "file_id": file_id,
        "filename": safe_name,
        "size": len(content),
        "content_type": file.content_type or "application/octet-stream",
        "path": str(dest),
        "uploaded_at": api.datetime.datetime.now(api.datetime.timezone.utc).isoformat(),
    }
    return {"code": 0, "message": "File uploaded", "data": file_info}


@router.get("/uploads")
async def list_console_uploads(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """列出**本人**已上传文件"""
    scope = _user_scope(current_user)
    files = []
    for f in sorted(scope.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file():
            files.append(
                {
                    "filename": f.name,
                    "size": f.stat().st_size,
                    "modified": f.stat().st_mtime,
                }
            )
    from . import console as api

    files.sort(key=lambda x: x["modified"], reverse=True)
    for f in files:
        f["modified"] = api.datetime.datetime.fromtimestamp(f["modified"]).isoformat()
    return {"code": 0, "message": "success", "data": {"files": files, "total": len(files)}}


@router.get("/uploads/{filename}")
async def get_console_upload(
    filename: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """下载文件（仅本人域内）"""
    from . import console as api
    scope = _user_scope(current_user)
    safe = api._safe_filename(filename)
    path = scope / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return api.FileResponse(str(path), filename=safe)


@router.delete("/uploads/{filename}")
async def delete_console_upload(
    filename: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """删除文件（仅本人域内）"""
    scope = _user_scope(current_user)
    from . import console as api

    safe = api._safe_filename(filename)
    path = scope / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    path.unlink()
    return {"code": 0, "message": "File deleted"}
