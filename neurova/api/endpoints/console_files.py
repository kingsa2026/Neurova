"""Console file endpoints; runtime state remains owned by console."""
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from neurova.api.deps import get_current_user

router = APIRouter()


@router.post("/upload")
async def post_console_upload(
    request: Request,
    file: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """上传文件（BUG AUDIT S-08: 原零鉴权, 匿名可投递任意文件）"""
    from . import console as api
    safe_name = api._safe_filename(file.filename or "unnamed")
    file_id = str(api.uuid.uuid4())[:8]
    dest = api._CONSOLE_UPLOAD_DIR / f"{file_id}_{safe_name}"

    content = await file.read()
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
    """列出已上传文件"""
    from . import console as api
    files = []
    for f in sorted(api._CONSOLE_UPLOAD_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file():
            files.append(
                {
                    "filename": f.name,
                    "size": f.stat().st_size,
                    "modified": api.datetime.datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                }
            )
    return {"code": 0, "message": "success", "data": {"files": files, "total": len(files)}}


@router.get("/uploads/{filename}")
async def get_console_upload(
    filename: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """下载文件"""
    from . import console as api
    safe = api._safe_filename(filename)
    path = api._CONSOLE_UPLOAD_DIR / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return api.FileResponse(str(path), filename=safe)


@router.delete("/uploads/{filename}")
async def delete_console_upload(
    filename: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """删除文件"""
    from . import console as api
    safe = api._safe_filename(filename)
    path = api._CONSOLE_UPLOAD_DIR / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    path.unlink()
    return {"code": 0, "message": "File deleted"}
