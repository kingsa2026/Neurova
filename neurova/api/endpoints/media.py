"""
Media Storage API - 媒体存储管理接口

功能:
- POST /api/v1/media/save - 保存媒体文件
- GET /api/v1/media/{media_id} - 获取媒体文件
- GET /api/v1/media/{media_id}/metadata - 获取媒体元数据
- GET /api/v1/media/list - 列出媒体文件（支持 search 过滤 filename/media_id）
- DELETE /api/v1/media/{media_id} - 删除媒体文件
- POST /api/v1/media/batch-delete - 批量删除媒体文件
- GET /api/v1/media/stats/{agent_id} - 获取存储统计
- GET /api/v1/media/memory/{memory_id} - 获取关联记忆的媒体
- GET /api/v1/media/config - 获取媒体存储配置
- PUT /api/v1/media/config - 更新媒体存储配置
- POST /api/v1/media/cache/clear - 清除媒体存储缓存
- GET /api/v1/media/storage-path/{media_type} - 获取用户指定媒体类型的存储路径
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from neurova.api.auth import get_current_user, Depends
from pydantic import BaseModel, Field
from neurova.core.data_root import dataPath

logger = get_logger(__name__)
router = APIRouter(dependencies=[Depends(get_current_user)],)

#: `DELETE /{media_id}` 与 `/batch-delete` 共用的两种模式（放在模型之前：`Field(default=…)`
#: 在建类时求值，常量住得比模型晚就是 NameError）。
#: **默认是 permanent**——现役页面（`AgentMediaPage`）的「删了就没了」是对用户的既有承诺，
#: 翻成软删属隐私语义变更，不在 §6-158 那笔裁定的授权内。
DELETE_MODES = ("trash", "permanent")
DEFAULT_DELETE_MODE = "permanent"


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class BatchDeleteRequest(BaseModel):
    """批量删除请求（F-1 契约对齐：NeurUI batchDeleteMedia）"""

    media_ids: List[str] = Field(..., description="要删除的媒体 ID 列表")
    mode: str = Field(default=DEFAULT_DELETE_MODE,
                      description="trash＝移入回收站（字节保留）；缺省 permanent＝直接删除"
                                  "（与单条 DELETE 同一口径，默认档不翻转）")


class UpdateConfigRequest(BaseModel):
    """更新配置请求"""

    max_file_size: Optional[int] = Field(default=None, description="最大文件大小 (bytes)")
    allowed_types: Optional[List[str]] = Field(default=None, description="允许的媒体类型")
    storage_path: Optional[str] = Field(default=None, description="存储路径")
    enable_compression: Optional[bool] = Field(default=None, description="是否启用压缩")


# ---------------------------------------------------------------------------
# 持久化存储（2026-09-12 P8：原纯内存——上传文件字节在盘上但索引重启即丢，
# AgentMediaPage 列表恒空且孤儿文件不可管；config 保存同样不落盘）
# ---------------------------------------------------------------------------

_INDEX_FILE = os.environ.get("NEUROVA_MEDIA_INDEX_PATH") or dataPath("media_index.json")
_CONFIG_FILE = os.environ.get("NEUROVA_MEDIA_CONFIG_PATH") or dataPath("media_config.json")

_media_store: Dict[str, Dict[str, Any]] = {}
# 索引的"改 dict + 整份 dump"必须同属一个临界区：否则两路上传并发时，后写那次 dump
# 用的是先写那次落盘**之前**抓的快照，条目会被静默覆盖掉（§6-139；manager.py 那份原本
# 有 `self._lock`，端点自持这份此前是裸 dict + 裸 dump）。
_INDEX_LOCK = threading.RLock()
_media_config: Dict[str, Any] = {
    "max_file_size": 50 * 1024 * 1024,  # 50MB
    "allowed_types": ["image", "audio", "video", "file"],
    "storage_path": "media_storage",
    "enable_compression": False,
    "created_at": time.time(),
    "updated_at": time.time(),
}


def _load_index() -> None:
    try:
        with open(_INDEX_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            # 重启后磁盘文件被外部清理的行剔除（files_api hydrate 同口径）
            for mid, rec in (raw.get("media", {}) or {}).items():
                sp = rec.get("storage_path")
                if sp and not Path(os.path.abspath(sp)).exists():
                    continue
                _media_store[mid] = rec
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to load media index: %s", e)


def _save_index() -> None:
    p = Path(_INDEX_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(
        json.dumps({"media": _media_store}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    tmp.replace(p)


def _load_config() -> None:
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            _media_config.update(saved)
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to load media config: %s", e)


def _save_config() -> None:
    p = Path(_CONFIG_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(_media_config, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


_load_index()
_load_config()

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _generate_media_id() -> str:
    """生成媒体 ID"""
    return f"media-{uuid.uuid4().hex[:12]}"


def _storage_root() -> Path:
    """媒体存储根目录（磁盘内容源的基准路径），**一律返回绝对路径**。

    三种入落点在这里收成一处：未配置 → 数据根下的 `media_storage/`；配置成绝对路径 → 照用；
    配置成相对名（模块默认值 `"media_storage"` 就是这一形）→ **锚到数据根**，不留给 CWD。
    原先相对名会一路带到 `is_relative_to()` 那里去比一个绝对路径，于是每次上传都 400
    「非法的存储路径」（§6-158 的活体跑第一步就撞上，实据与判据见
    `TestStorageRootIsNeverCwdRelative`）——这一族的既有口径是「运行期落点全量锚定数据根」
    （`c2cb809c`/`721ef038`），不是在下层加"看着相对就当数据根"的兜底判断。
    """
    from neurova.core.data_root import get_data_root

    root = get_data_root()
    configured = str(_media_config.get("storage_path") or "").strip()
    if not configured:
        return root / "media_storage"
    candidate = Path(configured)
    return candidate if candidate.is_absolute() else (root / candidate).resolve()


def _media_disk_path(media: Dict[str, Any]) -> Path:
    """把元数据里的 storage_path 解析为磁盘绝对路径。"""
    path = Path(media.get("storage_path") or "")
    return path if path.is_absolute() else Path(os.path.abspath(path))


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


def _content_disposition(filename: Optional[str]) -> str:
    """RFC 6266/5987 Content-Disposition（资源修复 #6, 台账 2026-09-11）：

    filename= 用 ASCII 安全名（含引号/换行的名字一并回退，防响应头注入）；
    非 ASCII 原始名经 filename*=UTF-8''<percent-encoded> 传递——旧实现把
    原始名直写响应头，中文文件名下载头异常。
    """
    name = filename or "file"
    if name.isascii() and not re.search(r'["\\\r\n]', name):
        return f'attachment; filename="{name}"'
    fallback = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80] or "download"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"


def _remove_media_entry(media_id: str) -> Optional[Dict[str, Any]]:
    """删除单个媒体（磁盘文件 + 内存元数据）。

    返回被删的元数据；media_id 不存在时返回 None。
    """
    media = _media_store.get(media_id)
    if not media:
        return None

    # P1-2: 内容已落盘，删元数据须同步删磁盘文件
    disk_path = _media_disk_path(media)
    try:
        if disk_path.is_file():
            disk_path.unlink()
    except OSError as e:
        logger.warning("删除媒体磁盘文件失败 %s: %s", disk_path, e)

    with _INDEX_LOCK:
        del _media_store[media_id]
        _save_index()
    return media


# ---------------------------------------------------------------------------
# 回收站（§6-158，裁定乙）：软删/读面/恢复/彻底删除四件，默认语义一律不变
# 模式常量在模块顶部（`DELETE_MODES` / `DEFAULT_DELETE_MODE`），两个删除口共用一份。
# ---------------------------------------------------------------------------


def _isTrashed(record: Dict[str, Any]) -> bool:
    """回收站行的唯一判据。现役读面（三个列表口径＋三个取物口径）都只看这一处——
    各处各写一遍 `rec.get("is_deleted")` 就是"漏最后那一处排除"的成因。"""
    return bool(record.get("is_deleted"))


def _liveMedia(media_id: str) -> Optional[Dict[str, Any]]:
    """按 id 取「不在回收站」的那一行；三个取物口径共用这份单点。"""
    record = _media_store.get(media_id)
    if not record or _isTrashed(record):
        return None
    return record


def _activeMedia() -> List[Dict[str, Any]]:
    """活条目全集——`/list`、`/stats`、`/memory` 三个列表面从这里取，不再各自 `values()`。"""
    return [m for m in _media_store.values() if not _isTrashed(m)]


def _trashMediaEntry(media_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """移入回收站：只打标记，字节留在盘上（否则"恢复"无从谈起）。

    返回 `(行, 拒因)`；拒因为空即成功。拒因由端点映射成诚实的 4xx，不在这层抛 HTTP 细节。
    """
    record = _media_store.get(media_id)
    if not record:
        return None, "notFound"
    if _isTrashed(record):
        return None, "alreadyTrashed"
    with _INDEX_LOCK:
        record["is_deleted"] = True
        record["deleted_at"] = time.time()
        _save_index()
    return record, ""


def _restoreMediaEntry(media_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """从回收站恢复：字节必须仍在，否则不许造一条「活但取不到」的记录。"""
    record = _media_store.get(media_id)
    if not record:
        return None, "notFound"
    if not _isTrashed(record):
        return None, "notTrashed"
    if not _media_disk_path(record).is_file():
        return None, "contentMissing"
    with _INDEX_LOCK:
        record["is_deleted"] = False
        record.pop("deleted_at", None)
        _save_index()
    return record, ""


_REJECTION_HTTP = {
    "notFound": (404, "媒体不存在"),
    "alreadyTrashed": (409, "该条目已在回收站"),
    "notTrashed": (409, "该条目不在回收站"),
    "contentMissing": (410, "回收站条目的内容文件已不在盘上，无法恢复"),
}


def _reject(reason: str) -> HTTPException:
    code, detail = _REJECTION_HTTP[reason]
    return HTTPException(status_code=code, detail=detail)


def _uploaderOr401(current_user: Dict[str, Any]) -> str:
    """登录态 → 上传者；不可归因时显式 401，不写进索引。

    `_user_identity` 对**无 `sub` 的合法签名令牌**兜成 `"unknown"`（`api/auth.py:627`）。
    照直记下就是批 12 那枚「usage 落 anonymous」的同形缺陷：归属那一格看着有值，
    其实谁都不是，事后按人筛产物会筛出一堆假账号。
    """
    user_id = str(current_user.get("user_id") or "")
    if not user_id or user_id == "unknown":
        raise HTTPException(
            status_code=401, detail="缺少可归因的登录身份（令牌无 sub），无法记录上传者")
    return user_id

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/save")
async def save_media(
    file: UploadFile = File(...),
    media_type: str = Form(...),
    agent_id: str = Form(default="default"),
    memory_id: Optional[str] = Form(default=None),
    metadata: Optional[str] = Form(default=None),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """保存上传的媒体文件

    归属只从登录态取（§6-172）：这一格此前是**可选表单字段**，而现役前端从不传它，
    于是索引里每条媒体记录的 `user_id` 恒为 null——归属从未被写侧填过。
    "让前端补传"不是替代方案：`user_id` 是标识不是凭证，收下就等于允许任何人
    把产物记到别人名下。
    """
    uploaderId = _uploaderOr401(current_user)
    # 验证媒体类型
    if media_type not in _media_config.get("allowed_types", []):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的媒体类型: {media_type}。允许的类型: {_media_config.get('allowed_types', [])}",
        )

    # 检查文件大小：分块读累计校验，超限立即 413 并停止读取。
    # P1-2: 原实现 await file.read() 先全量读入内存再校验，单请求可打进任意大内存。
    max_size = _media_config.get("max_file_size", 50 * 1024 * 1024)

    media_id = _generate_media_id()
    filename = file.filename or f"unnamed_{media_id}"
    mime_type = _get_mime_type(media_type, filename)

    # 存储路径（P1-2: 内容真实落盘，路径必须防逃逸——agent_id/文件名可能携带路径片段）
    storage_path = str(_storage_root() / agent_id / media_type / f"{media_id}_{filename}")
    disk_path = Path(os.path.abspath(storage_path))
    if not disk_path.is_relative_to(_storage_root()):
        raise HTTPException(status_code=400, detail="非法的存储路径（agent_id 或文件名包含路径片段）")

    disk_path.parent.mkdir(parents=True, exist_ok=True)

    # 解析元数据
    meta = {}
    if metadata:
        try:
            import json

            meta = json.loads(metadata)
        except Exception:
            meta = {"raw_metadata": metadata}

    size = 0
    # 校验位随字节流一起算（分块读已是既有形态，不额外把整份读进内存）：
    # 产物落盘后要能证明它还是当初那份——这格能力并自退役的 media/manager.py（§6-139）
    digest = hashlib.sha256()
    try:
        with disk_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_size:
                    raise HTTPException(
                        status_code=413, detail=f"文件大小超过限制 ({size} > {max_size} bytes)"
                    )
                digest.update(chunk)
                out.write(chunk)
    except HTTPException:
        # 超限中断：清掉半写文件后原样抛出
        try:
            disk_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    except OSError as e:
        try:
            disk_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail=f"媒体文件写入失败: {e}")

    now = time.time()
    media_info = {
        "media_id": media_id,
        "filename": filename,
        "media_type": media_type,
        "mime_type": mime_type,
        "size": size,
        "agent_id": agent_id,
        "user_id": uploaderId,
        "memory_id": memory_id,
        "storage_path": storage_path,
        "created_at": now,
        "checksum": digest.hexdigest(),
        "metadata": meta,
        # 每一行都带这个键，索引里就只有一种形状（缺键行与 False 行两种状态并存时，
        # 读面的"排除回收站"总会有一处按 falsy 兜过去，看不出它其实管的是两种形态）
        "is_deleted": False,
    }

    with _INDEX_LOCK:
        _media_store[media_id] = media_info
        _save_index()

    return {
        "code": 0,
        "message": f"媒体文件 '{filename}' 保存成功",
        "data": media_info,
    }


@router.get("/list")
async def list_media(
    agent_id: str = Query(default="default", description="Agent ID"),
    media_type: Optional[str] = Query(default=None, description="媒体类型筛选"),
    search: Optional[str] = Query(
        default=None, description="搜索关键词（不区分大小写匹配 filename/media_id，空串视同不过滤）"
    ),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
):
    """列出媒体文件（search 后端过滤，total 反映过滤后总数，分页语义不变）。"""
    media_list = [m for m in _activeMedia() if m.get("agent_id") == agent_id]

    if media_type:
        media_list = [m for m in media_list if m.get("media_type") == media_type]

    # 台账 2026-09-11 ③：搜索后端化——旧前端过滤只覆盖已加载 limit 页，
    # 大数据量搜不到未加载条目。filename/media_id 不区分大小写子串匹配。
    q = (search or "").strip().lower()
    if q:
        media_list = [
            m for m in media_list
            if q in m.get("filename", "").lower() or q in m.get("media_id", "").lower()
        ]

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


@router.get("/config")
async def get_config():
    """获取媒体存储配置（F-1 路由顺序锚：字面段路由必须注册在
    GET /{media_id} 之前，否则被参数路由吞掉 404 "Media 'config' not found"）。"""
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
    _save_config()

    return {
        "code": 0,
        "message": "媒体存储配置已更新",
        "data": _media_config.copy(),
    }


@router.post("/batch-delete")
async def batch_delete_media(body: BatchDeleteRequest):
    """批量删除媒体文件（F-1 契约对齐：前端 batchDeleteMedia）。

    逐个处理（不中断整批），模式与单条 `DELETE /{media_id}` 共用 `DELETE_MODES` 那一份口径，
    缺省同样是 permanent。不存在的 ID 沿用既有 reason 串——前端按它渲染失败清单。
    """
    if body.mode not in DELETE_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"未知的删除模式: {body.mode}（可用：{' / '.join(DELETE_MODES)}）",
        )

    succeeded: List[str] = []
    failed: List[Dict[str, str]] = []
    for media_id in body.media_ids:
        if body.mode == "trash":
            media, reason = _trashMediaEntry(media_id)
        else:
            media, reason = _remove_media_entry(media_id), "notFound"
        if media is None:
            failed.append({
                "media_id": media_id,
                "reason": "media not found" if reason == "notFound"
                else _REJECTION_HTTP[reason][1],
            })
        else:
            succeeded.append(media_id)

    return {
        "code": 0,
        "message": f"批量删除完成: 成功 {len(succeeded)} 个, 失败 {len(failed)} 个",
        "data": {"succeeded": succeeded, "failed": failed},
    }


@router.get("/trash")
async def list_trash(
    agent_id: Annotated[str, Query(description="Agent ID")] = "default",
    limit: Annotated[int, Query(le=200)] = 50,
    offset: int = 0,
):
    """回收站读面（§6-158）：软删条目必须**有人能读**，否则又是一处「只写不读」的断点。

    单段字面路由，注册在 `GET /{media_id}` 之前（台账 2026-09-11 ⑤ 的那道锚）。
    保留策略同日人裁：**永久保留直到用户显式彻底删除**——不设 TTL、不做自动过期，
    媒体是用户内容，自动删等于替用户决定。
    """
    trashed = [m for m in _media_store.values()
               if _isTrashed(m) and m.get("agent_id") == agent_id]
    trashed.sort(key=lambda m: m.get("deleted_at", 0), reverse=True)

    return {
        "code": 0,
        "data": {
            "media": trashed[offset: offset + limit],
            "total": len(trashed),
            "offset": offset,
            "limit": limit,
        },
    }


@router.get("/{media_id}")
async def get_media(media_id: str):
    """获取媒体文件内容（P1-2: 从磁盘 FileResponse 流式读取，不再驻留内存）"""
    media = _liveMedia(media_id)
    if not media:
        raise HTTPException(status_code=404, detail=f"Media '{media_id}' not found")

    disk_path = _media_disk_path(media)
    if not disk_path.is_file():
        raise HTTPException(status_code=404, detail=f"Media content not found")

    return FileResponse(
        path=disk_path,
        media_type=media.get("mime_type", "application/octet-stream"),
        headers={
            "Content-Disposition": _content_disposition(media.get("filename")),
            "X-Media-ID": media_id,
        },
    )


@router.get("/{media_id}/metadata")
async def get_media_metadata(media_id: str):
    """获取媒体文件元数据（含**真读盘重算**的校验位判定）。"""
    media = _liveMedia(media_id)
    if not media:
        raise HTTPException(status_code=404, detail=f"Media '{media_id}' not found")

    stored = media.get("checksum")
    disk_path = _media_disk_path(media)
    checksum_ok: Optional[bool] = None
    if stored:
        checksum_ok = False          # 读不到或哈希不符都算不通过，不因缺文件而回 True
        digest = hashlib.sha256()
        try:
            with disk_path.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    digest.update(chunk)
            checksum_ok = digest.hexdigest() == stored
        except OSError as e:
            logger.warning("媒体校验读取失败 %s: %s", disk_path, e)

    return {
        "code": 0,
        "data": {
            "media_id": media.get("media_id"),
            "filename": media.get("filename"),
            "media_type": media.get("media_type"),
            "mime_type": media.get("mime_type"),
            "size": media.get("size"),
            "created_at": media.get("created_at"),
            # 归属要有读面：写侧填了而元数据回不出来，就又是一次「只写不读」（§6-172）
            "user_id": media.get("user_id"),
            "checksum": stored,
            "checksum_ok": checksum_ok,
            "metadata": media.get("metadata", {}),
        },
    }


@router.post("/{media_id}/restore")
async def restore_media(media_id: str):
    """从回收站恢复。字节已不在即 410——不许把"恢复失败"折成 200，
    留下一条列表里看得见、取字节却 404 的活记录。"""
    media, reason = _restoreMediaEntry(media_id)
    if media is None:
        raise _reject(reason)

    return {
        "code": 0,
        "message": f"媒体文件 '{media.get('filename')}' 已恢复",
        "data": {"media_id": media_id},
    }


@router.get("/download/{media_id}")
async def download_attachment(media_id: str):
    """直接从附件目录下载文件（用于TTS音频等；P1-2: 磁盘流式读取）"""
    media = _liveMedia(media_id)
    if not media:
        raise HTTPException(status_code=404, detail=f"Media '{media_id}' not found")

    disk_path = _media_disk_path(media)
    if not disk_path.is_file():
        raise HTTPException(status_code=404, detail=f"Media content not found")

    return FileResponse(
        path=disk_path,
        media_type=media.get("mime_type", "application/octet-stream"),
        headers={
            "Content-Disposition": _content_disposition(media.get("filename")),
        },
    )


@router.delete("/{media_id}")
async def delete_media(
    media_id: str,
    mode: Annotated[
        str,
        Query(description="trash＝移入回收站（字节保留、可从 /trash 读回）；"
                          "缺省 permanent＝直接删除（现役页面的既有承诺）"),
    ] = DEFAULT_DELETE_MODE,
):
    """删除媒体文件。模式只认 `DELETE_MODES` 那一份口径：坏档当场 400，
    既不动盘上字节也不落软删标记（不许兜底成任何一种删除）。

    默认值写成 `Annotated[...] = "permanent"` 而不是 `mode: str = Query(default=...)`：
    后者把 `Query` 对象当成 Python 缺省值，**直接按函数调用**的既有判据
    （`test_media_disk_storage.py` 两处）会拿到一个描述对象并撞上"未知模式"——
    A/B 实测到的本批自伤，形态记在台账 §6-158。
    """
    if mode not in DELETE_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"未知的删除模式: {mode}（可用：{' / '.join(DELETE_MODES)}）",
        )

    if mode == "trash":
        media, reason = _trashMediaEntry(media_id)
        if media is None:
            raise _reject(reason)
        return {
            "code": 0,
            "message": f"媒体文件 '{media.get('filename')}' 已移入回收站",
            "data": {"mode": "trash", "media_id": media_id},
        }

    media = _remove_media_entry(media_id)
    if media is None:
        raise HTTPException(status_code=404, detail=f"Media '{media_id}' not found")

    return {
        "code": 0,
        "message": f"媒体文件 '{media.get('filename')}' 已删除",
    }


@router.get("/stats/{agent_id}")
async def get_media_stats(agent_id: str):
    """获取媒体存储统计信息。

    台账 2026-09-11 ⑤：前端无 /stats 消费（getMediaStats 已移除且 vitest 锁定），
    故有意不补 GET /stats 单段变体——单段字面路由若新增须注册在 /{media_id}
    之前（守卫见 tests/unit/api/test_media_route_order_guard.py）。
    """
    agent_media = [m for m in _activeMedia() if m.get("agent_id") == agent_id]

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
    memory_media = [m for m in _activeMedia() if m.get("memory_id") == memory_id]

    return {
        "code": 0,
        "data": {
            "memory_id": memory_id,
            "media": memory_media,
            "total": len(memory_media),
        },
    }


@router.post("/cache/clear")
async def clear_cache():
    """清除媒体存储缓存（P1-2 实做：清空内存媒体索引）。

    磁盘文件是持久化内容源，不随缓存清除删除（逐条删除走 DELETE /{media_id}）。
    """
    cleared_items = len(_media_store)
    freed_space = sum(m.get("size", 0) for m in _media_store.values())
    _media_store.clear()
    return {
        "code": 0,
        "message": "媒体存储缓存已清除",
        "data": {
            "cleared_items": cleared_items,
            "freed_space": freed_space,
        },
    }


@router.get("/storage-path/{media_type}")
async def get_user_storage_path(
    media_type: str,
    agent_id: str = Query(default="default", description="Agent ID"),
    user_id: Optional[str] = Query(default=None, description="用户 ID"),
):
    """获取用户指定媒体类型的存储路径"""
    base_path = str(_storage_root())

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
