"""
Media Storage API - 媒体存储管理接口

功能:
- POST /api/v1/media/save - 保存媒体文件
- GET /api/v1/media/{media_id} - 获取媒体文件
- GET /api/v1/media/{media_id}/metadata - 获取媒体元数据
- GET /api/v1/media/list - 列出媒体文件
- DELETE /api/v1/media/{media_id} - 删除媒体文件
- GET /api/v1/media/stats/{agent_id} - 获取存储统计
- GET /api/v1/media/memory/{memory_id} - 获取关联记忆的媒体
- GET /api/v1/media/config - 获取媒体存储配置
- PUT /api/v1/media/config - 更新媒体存储配置
- POST /api/v1/media/cache/clear - 清除媒体存储缓存
- GET /api/v1/media/storage-path/{media_type} - 获取用户指定媒体类型的存储路径
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class SaveMediaRequest(BaseModel):
    """保存媒体请求"""

    media_type: str = Field(..., description="媒体类型 (image, audio, video, file)")
    agent_id: str = Field(default="default", description="Agent ID")
    user_id: Optional[str] = Field(default=None, description="用户 ID")
    memory_id: Optional[str] = Field(default=None, description="关联记忆 ID")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="附加元数据")


class MediaListRequest(BaseModel):
    """媒体列表请求"""

    agent_id: str = Field(default="default", description="Agent ID")
    media_type: Optional[str] = Field(default=None, description="媒体类型筛选")
    limit: int = Field(default=50, le=200, description="返回数量")
    offset: int = Field(default=0, description="偏移量")


class UpdateConfigRequest(BaseModel):
    """更新配置请求"""

    max_file_size: Optional[int] = Field(default=None, description="最大文件大小 (bytes)")
    allowed_types: Optional[List[str]] = Field(default=None, description="允许的媒体类型")
    storage_path: Optional[str] = Field(default=None, description="存储路径")
    enable_compression: Optional[bool] = Field(default=None, description="是否启用压缩")


class MediaInfo(BaseModel):
    """媒体信息"""

    media_id: str
    filename: str
    media_type: str
    mime_type: str
    size: int
    agent_id: str
    user_id: Optional[str] = None
    memory_id: Optional[str] = None
    storage_path: str
    created_at: float
    metadata: Dict[str, Any] = {}


class MediaStats(BaseModel):
    """媒体统计"""

    total_files: int
    total_size: int
    by_type: Dict[str, Dict[str, Any]]
    by_agent: Dict[str, Dict[str, Any]]


# ---------------------------------------------------------------------------
# In-Memory Store
# ---------------------------------------------------------------------------

_media_store: Dict[str, Dict[str, Any]] = {}
_media_config: Dict[str, Any] = {
    "max_file_size": 50 * 1024 * 1024,  # 50MB
    "allowed_types": ["image", "audio", "video", "file"],
    "storage_path": "media_storage",
    "enable_compression": False,
    "created_at": time.time(),
    "updated_at": time.time(),
}

# 模拟文件内容存储
_file_contents: Dict[str, bytes] = {}


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _generate_media_id() -> str:
    """生成媒体 ID"""
    return f"media-{uuid.uuid4().hex[:12]}"


def _get_mime_type(media_type: str, filename: str) -> str:
    """获取 MIME 类型"""
    ext = os.path.splitext(filename)[1].lower() if filename else ""
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".mp4": "video/mp4",
        ".avi": "video/avi",
        ".mov": "video/quicktime",
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".json": "application/json",
    }
    return mime_map.get(ext, f"{media_type}/octet-stream")


def _get_media_manager():
    """获取或创建 MediaManager 实例"""
    try:
        from neurova.media import MediaManager

        return MediaManager.get_instance()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/save")
async def save_media(
    file: UploadFile = File(...),
    media_type: str = Form(...),
    agent_id: str = Form(default="default"),
    user_id: Optional[str] = Form(default=None),
    memory_id: Optional[str] = Form(default=None),
    metadata: Optional[str] = Form(default=None),
):
    """保存上传的媒体文件"""
    # 验证媒体类型
    if media_type not in _media_config.get("allowed_types", []):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的媒体类型: {media_type}。允许的类型: {_media_config.get('allowed_types', [])}",
        )

    # 检查文件大小
    content = await file.read()
    max_size = _media_config.get("max_file_size", 50 * 1024 * 1024)
    if len(content) > max_size:
        raise HTTPException(status_code=413, detail=f"文件大小超过限制 ({len(content)} > {max_size} bytes)")

    media_id = _generate_media_id()
    filename = file.filename or f"unnamed_{media_id}"
    mime_type = _get_mime_type(media_type, filename)

    # 模拟存储路径
    storage_path = os.path.join(
        _media_config.get("storage_path", "media_storage"), agent_id, media_type, f"{media_id}_{filename}"
    )

    # 解析元数据
    meta = {}
    if metadata:
        try:
            import json

            meta = json.loads(metadata)
        except Exception:
            meta = {"raw_metadata": metadata}

    now = time.time()
    media_info = {
        "media_id": media_id,
        "filename": filename,
        "media_type": media_type,
        "mime_type": mime_type,
        "size": len(content),
        "agent_id": agent_id,
        "user_id": user_id,
        "memory_id": memory_id,
        "storage_path": storage_path,
        "created_at": now,
        "metadata": meta,
    }

    _media_store[media_id] = media_info
    _file_contents[media_id] = content

    return {
        "code": 0,
        "message": f"媒体文件 '{filename}' 保存成功",
        "data": media_info,
    }


@router.get("/{media_id}")
async def get_media(media_id: str):
    """获取媒体文件内容"""
    media = _media_store.get(media_id)
    if not media:
        raise HTTPException(status_code=404, detail=f"Media '{media_id}' not found")

    content = _file_contents.get(media_id)
    if not content:
        raise HTTPException(status_code=404, detail=f"Media content not found")

    from fastapi.responses import Response

    return Response(
        content=content,
        media_type=media.get("mime_type", "application/octet-stream"),
        headers={
            "Content-Disposition": f"attachment; filename=\"{media.get('filename', 'file')}\"",
            "X-Media-ID": media_id,
        },
    )


@router.get("/{media_id}/metadata")
async def get_media_metadata(media_id: str):
    """获取媒体文件元数据"""
    media = _media_store.get(media_id)
    if not media:
        raise HTTPException(status_code=404, detail=f"Media '{media_id}' not found")

    return {
        "code": 0,
        "data": {
            "media_id": media.get("media_id"),
            "filename": media.get("filename"),
            "media_type": media.get("media_type"),
            "mime_type": media.get("mime_type"),
            "size": media.get("size"),
            "created_at": media.get("created_at"),
            "metadata": media.get("metadata", {}),
        },
    }


@router.get("/list")
async def list_media(
    agent_id: str = Query(default="default", description="Agent ID"),
    media_type: Optional[str] = Query(default=None, description="媒体类型筛选"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
):
    """列出媒体文件"""
    media_list = [m for m in _media_store.values() if m.get("agent_id") == agent_id]

    if media_type:
        media_list = [m for m in media_list if m.get("media_type") == media_type]

    # 按创建时间降序排序
    media_list.sort(key=lambda x: x.get("created_at", 0), reverse=True)

    total = len(media_list)
    paginated = media_list[offset : offset + limit]

    return {
        "code": 0,
        "data": {
            "media": paginated,
            "total": total,
            "offset": offset,
            "limit": limit,
        },
    }


@router.get("/download/{media_id}")
async def download_attachment(media_id: str):
    """直接从附件目录下载文件（用于TTS音频等）"""
    media = _media_store.get(media_id)
    if not media:
        raise HTTPException(status_code=404, detail=f"Media '{media_id}' not found")

    content = _file_contents.get(media_id)
    if not content:
        raise HTTPException(status_code=404, detail=f"Media content not found")

    from fastapi.responses import Response

    return Response(
        content=content,
        media_type=media.get("mime_type", "application/octet-stream"),
        headers={
            "Content-Disposition": f"attachment; filename=\"{media.get('filename', 'file')}\"",
        },
    )


@router.delete("/{media_id}")
async def delete_media(media_id: str):
    """删除媒体文件"""
    media = _media_store.get(media_id)
    if not media:
        raise HTTPException(status_code=404, detail=f"Media '{media_id}' not found")

    # 删除文件内容
    _file_contents.pop(media_id, None)

    # 删除元数据
    del _media_store[media_id]

    return {
        "code": 0,
        "message": f"媒体文件 '{media.get('filename')}' 已删除",
    }


@router.get("/stats/{agent_id}")
async def get_media_stats(agent_id: str):
    """获取媒体存储统计信息"""
    agent_media = [m for m in _media_store.values() if m.get("agent_id") == agent_id]

    total_files = len(agent_media)
    total_size = sum(m.get("size", 0) for m in agent_media)

    # 按类型统计
    by_type: Dict[str, Dict[str, Any]] = {}
    for m in agent_media:
        media_type = m.get("media_type", "unknown")
        if media_type not in by_type:
            by_type[media_type] = {"count": 0, "size": 0}
        by_type[media_type]["count"] += 1
        by_type[media_type]["size"] += m.get("size", 0)

    # 按 Agent 统计（这里只有一个 agent）
    by_agent: Dict[str, Dict[str, Any]] = {agent_id: {"count": total_files, "size": total_size}}

    return {
        "code": 0,
        "data": {
            "agent_id": agent_id,
            "total_files": total_files,
            "total_size": total_size,
            "by_type": by_type,
            "by_agent": by_agent,
        },
    }


@router.get("/memory/{memory_id}")
async def get_memory_media(memory_id: str):
    """获取与指定记忆关联的媒体文件"""
    memory_media = [m for m in _media_store.values() if m.get("memory_id") == memory_id]

    return {
        "code": 0,
        "data": {
            "memory_id": memory_id,
            "media": memory_media,
            "total": len(memory_media),
        },
    }


@router.get("/config")
async def get_config():
    """获取媒体存储配置"""
    return {
        "code": 0,
        "data": _media_config.copy(),
    }


@router.put("/config")
async def update_config(body: UpdateConfigRequest):
    """更新媒体存储配置"""
    if body.max_file_size is not None:
        _media_config["max_file_size"] = body.max_file_size
    if body.allowed_types is not None:
        _media_config["allowed_types"] = body.allowed_types
    if body.storage_path is not None:
        _media_config["storage_path"] = body.storage_path
    if body.enable_compression is not None:
        _media_config["enable_compression"] = body.enable_compression

    _media_config["updated_at"] = time.time()

    return {
        "code": 0,
        "message": "媒体存储配置已更新",
        "data": _media_config.copy(),
    }


@router.post("/cache/clear")
async def clear_cache():
    """清除媒体存储缓存"""
    # 这里只是模拟清除缓存
    return {
        "code": 0,
        "message": "媒体存储缓存已清除",
        "data": {
            "cleared_items": 0,
            "freed_space": 0,
        },
    }


@router.get("/storage-path/{media_type}")
async def get_user_storage_path(
    media_type: str,
    agent_id: str = Query(default="default", description="Agent ID"),
    user_id: Optional[str] = Query(default=None, description="用户 ID"),
):
    """获取用户指定媒体类型的存储路径"""
    base_path = _media_config.get("storage_path", "media_storage")

    if user_id:
        path = os.path.join(base_path, agent_id, user_id, media_type)
    else:
        path = os.path.join(base_path, agent_id, media_type)

    return {
        "code": 0,
        "data": {
            "media_type": media_type,
            "agent_id": agent_id,
            "user_id": user_id,
            "storage_path": path,
            "absolute_path": os.path.abspath(path),
        },
    }
