from __future__ import annotations

"""
通知管理接口 - Notifications Endpoint

功能:
1. 获取通知列表 (GET /api/v1/notifications)
2. 未读数 (GET /api/v1/notifications/unread-count)
3. 标记已读 (POST|PUT /api/v1/notifications/{id}/read)
4. 全部已读 (POST /api/v1/notifications/mark-all-read, PUT read-all 兼容)
5. 删除通知 (DELETE /api/v1/notifications/{id})
6. 推送统计 (GET /api/v1/notifications/push-statistics)

契约 (2026-09-01 对齐前端 api/modules/notifications.ts):
- 响应统一 {code, message, data} 信封; 列表 data={items, total}
- 条目字段 id/type/title/message/read/created_at(ISO)/data
- JSON 文件持久化 (NEUROVA_NOTIFICATIONS_PATH, 默认 data/notifications.json)

通知门面 (生产者统一入口):
    notify_user / notify_admins / notify_all_users
"""

import asyncio
import datetime
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path as FsPath
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from neurova.api.auth import get_current_user_or_default
from neurova.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

_DEFAULT_STORAGE = "./data/notifications.json"


@dataclass
class Notification:
    """通知数据结构"""

    notification_id: str
    user_id: str
    title: str
    message: str
    notification_type: str = "info"
    read: bool = False
    created_at: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)


class NotificationManager:
    """通知管理器（JSON 文件持久化 + RLock 并发保护）"""

    def __init__(self, storage_path: Optional[str] = None):
        self._storage_path = FsPath(
            storage_path or os.environ.get("NEUROVA_NOTIFICATIONS_PATH") or _DEFAULT_STORAGE
        )
        self._notifications: Dict[str, Notification] = {}
        self._user_notifications: Dict[str, List[str]] = {}  # user_id -> notification_ids
        self._lock = threading.RLock()
        self._load()

    # ── 持久化 ──────────────────────────────────────────

    def _load(self) -> None:
        if not self._storage_path.exists():
            return
        try:
            raw = json.loads(self._storage_path.read_text(encoding="utf-8"))
            for nid, item in (raw.get("notifications") or {}).items():
                self._notifications[nid] = Notification(
                    notification_id=nid,
                    user_id=item.get("user_id", ""),
                    title=item.get("title", ""),
                    message=item.get("message", ""),
                    notification_type=item.get("notification_type", "info"),
                    read=bool(item.get("read")),
                    created_at=float(item.get("created_at", 0.0)),
                    data=item.get("data") or {},
                )
            for uid, ids in (raw.get("index") or {}).items():
                self._user_notifications[uid] = [i for i in ids if i in self._notifications]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load notifications from %s: %s", self._storage_path, exc)

    def _save(self) -> None:
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "notifications": {
                    nid: {
                        "user_id": n.user_id,
                        "title": n.title,
                        "message": n.message,
                        "notification_type": n.notification_type,
                        "read": n.read,
                        "created_at": n.created_at,
                        "data": n.data,
                    }
                    for nid, n in self._notifications.items()
                },
                "index": self._user_notifications,
            }
            self._storage_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save notifications to %s: %s", self._storage_path, exc)

    def add_notification(
        self,
        user_id: str,
        title: str,
        message: str,
        notification_type: str = "info",
        data: Optional[Dict[str, Any]] = None,
    ) -> Notification:
        """添加通知"""
        with self._lock:
            notification_id = str(uuid.uuid4())
            notification = Notification(
                notification_id=notification_id,
                user_id=user_id,
                title=title,
                message=message,
                notification_type=notification_type,
                read=False,
                created_at=time.time(),
                data=data or {},
            )

            self._notifications[notification_id] = notification

            # 添加到用户索引
            if user_id not in self._user_notifications:
                self._user_notifications[user_id] = []
            self._user_notifications[user_id].append(notification_id)

            self._save()

            return notification

    def get_user_notifications(
        self,
        user_id: str,
        read: Optional[bool] = None,
        notification_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Notification]:
        """获取用户通知"""
        with self._lock:
            notification_ids = self._user_notifications.get(user_id, [])
            notifications = []

            for nid in notification_ids:
                if nid in self._notifications:
                    notification = self._notifications[nid]

                    # 应用过滤条件
                    if read is not None and notification.read != read:
                        continue
                    if notification_type and notification.notification_type != notification_type:
                        continue

                    notifications.append(notification)

            # 按时间倒序排序
            notifications.sort(key=lambda n: n.created_at, reverse=True)

            # 应用分页
            return notifications[offset : offset + limit]

    def get_notification(self, notification_id: str) -> Optional[Notification]:
        """获取单个通知"""
        return self._notifications.get(notification_id)

    def mark_as_read(self, notification_id: str, user_id: str) -> bool:
        """标记通知为已读"""
        with self._lock:
            notification = self._notifications.get(notification_id)
            if not notification:
                return False

            # 检查权限
            if notification.user_id != user_id:
                return False

            notification.read = True
            self._save()
            return True

    def mark_all_as_read(self, user_id: str) -> int:
        """标记用户所有通知为已读"""
        with self._lock:
            notification_ids = self._user_notifications.get(user_id, [])
            count = 0

            for nid in notification_ids:
                if nid in self._notifications:
                    notification = self._notifications[nid]
                    if not notification.read:
                        notification.read = True
                        count += 1

            if count:
                self._save()
            return count

    def delete_notification(self, notification_id: str, user_id: str) -> bool:
        """删除通知"""
        with self._lock:
            notification = self._notifications.get(notification_id)
            if not notification:
                return False

            # 检查权限
            if notification.user_id != user_id:
                return False

            # 从存储中删除
            del self._notifications[notification_id]

            # 从用户索引中删除
            if user_id in self._user_notifications:
                self._user_notifications[user_id] = [
                    nid for nid in self._user_notifications[user_id] if nid != notification_id
                ]

            self._save()

            return True

    def get_unread_count(self, user_id: str) -> int:
        """获取用户未读通知数量"""
        with self._lock:
            notification_ids = self._user_notifications.get(user_id, [])
            count = 0

            for nid in notification_ids:
                if nid in self._notifications:
                    notification = self._notifications[nid]
                    if not notification.read:
                        count += 1

            return count

    def get_push_statistics(self, user_id: str) -> Dict[str, Any]:
        """获取推送统计"""
        with self._lock:
            notification_ids = self._user_notifications.get(user_id, [])

            total = 0
            pushed = 0
            failed = 0

            for nid in notification_ids:
                if nid in self._notifications:
                    notification = self._notifications[nid]
                    if notification.notification_type == "task_completed":
                        total += 1
                        # 内存管理器无推送状态，默认未推送
                        failed += 1

            return {
                "total_task_notifications": total,
                "pushed_to_negative_screen": pushed,
                "push_failed": failed,
                "push_rate": pushed / total if total > 0 else 0.0,
            }


# 全局通知管理器单例
_notification_manager: Optional[NotificationManager] = None
_manager_lock = threading.Lock()


def get_notification_manager() -> NotificationManager:
    """获取全局通知管理器单例（NEUROVA_NOTIFICATIONS_PATH 隔离，默认落盘 data/）"""
    global _notification_manager
    if _notification_manager is None:
        with _manager_lock:
            if _notification_manager is None:
                _notification_manager = NotificationManager()
    return _notification_manager


def reset_notification_manager() -> None:
    """重置全局通知管理器（用于测试）"""
    global _notification_manager
    with _manager_lock:
        _notification_manager = None


# ── 通知门面（生产者统一入口） ────────────────────────────


def notify_user(
    user_id: str,
    title: str,
    message: str,
    notification_type: str = "info",
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """给单个用户发站内通知（幂等安全：异常只记日志不阻断业务）。"""
    try:
        get_notification_manager().add_notification(
            user_id=str(user_id),
            title=title,
            message=message,
            notification_type=notification_type,
            data=data or {},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify_user failed (user=%s): %s", user_id, exc)


def _admin_user_ids() -> List[str]:
    """枚举注册管理员 id（enhanced_users_api._users_store）。"""
    try:
        from neurova.api.endpoints import enhanced_users_api

        store = getattr(enhanced_users_api, "_users_store", None) or {}
        return [
            str(uid)
            for uid, info in store.items()
            if isinstance(info, dict) and info.get("role") == "admin"
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("enumerate admin users failed: %s", exc)
        return []


def notify_admins(
    title: str,
    message: str,
    notification_type: str = "info",
    data: Optional[Dict[str, Any]] = None,
) -> int:
    """给所有管理员发通知；无注册管理员时兜底 default（单机模式）。"""
    target_ids = _admin_user_ids() or ["default"]
    for uid in target_ids:
        notify_user(uid, title, message, notification_type, data)
    return len(target_ids)


def notify_all_users(
    title: str,
    message: str,
    notification_type: str = "info",
    data: Optional[Dict[str, Any]] = None,
) -> int:
    """给所有注册用户发通知；无注册用户时兜底 default。"""
    try:
        from neurova.api.endpoints import enhanced_users_api

        store = getattr(enhanced_users_api, "_users_store", None) or {}
        target_ids = [str(uid) for uid in store.keys()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("enumerate users failed: %s", exc)
        target_ids = []
    if not target_ids:
        target_ids = ["default"]
    for uid in target_ids:
        notify_user(uid, title, message, notification_type, data)
    return len(target_ids)


class NotificationItem(BaseModel):
    """通知条目（字段对齐前端 Notification 类型）"""

    id: str
    type: str
    title: str
    message: str
    read: bool = False
    created_at: str = ""
    data: Dict[str, Any] = {}


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _convert_notification_to_item(notification: Notification) -> NotificationItem:
    """Notification → API 条目（id/type/created_at ISO，对齐前端契约）"""
    created_at = datetime.datetime.fromtimestamp(
        notification.created_at, tz=datetime.timezone.utc
    ).isoformat()
    return NotificationItem(
        id=notification.notification_id,
        type=notification.notification_type,
        title=notification.title,
        message=notification.message,
        read=notification.read,
        created_at=created_at,
        data=notification.data,
    )


@router.get("", response_model=None)
async def get_notifications(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_default),
    read: Optional[bool] = Query(default=None, description="已读状态筛选"),
    notification_type: Optional[str] = Query(default=None, description="通知类型筛选"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
):
    """获取通知列表（信封 data={items, total}）"""
    try:
        user_id = current_user["user_id"]
        manager = get_notification_manager()

        all_matched = manager.get_user_notifications(
            user_id=user_id,
            read=read,
            notification_type=notification_type,
            limit=10_000,
            offset=0,
        )
        page_items = all_matched[offset : offset + limit]

        return {
            "code": 0,
            "message": "success",
            "data": {
                "items": [_convert_notification_to_item(n) for n in page_items],
                "total": len(all_matched),
            },
        }

    except Exception as e:
        logger.exception("Failed to get notifications: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to get notifications: {str(e)}"
        )


@router.get("/unread-count")
async def get_unread_count(request: Request, current_user: Dict[str, Any] = Depends(get_current_user_or_default)):
    """获取未读通知数量（data.total，前端铃铛消费）"""
    try:
        user_id = current_user["user_id"]
        manager = get_notification_manager()
        unread_count = manager.get_unread_count(user_id)

        return {
            "code": 0,
            "message": "success",
            "data": {"total": unread_count, "unread_count": unread_count},
        }

    except Exception as e:
        logger.exception("Failed to get unread count: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to get unread count: {str(e)}"
        )


@router.get("/stream")
async def stream_notifications(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_default),
    interval: float = Query(default=10.0, ge=2.0, le=60.0, description="轮询间隔秒"),
    max_events: Optional[int] = Query(default=None, ge=1, le=1000, description="最多发送帧数（测试钩子；生产不传=无限流）"),
):
    """未读数 SSE 流（补课 2.2：替代前端 60s 轮询）。

    事件 `data: {"type":"unread","count":N}`——仅 count 变化时发送；
    心跳注释行防代理超时。客户端断开自动收尾。鉴权与 REST 同源
    （fetch+ReadableStream 带 Bearer，不用 EventSource）。
    """
    user_id = current_user["user_id"]
    manager = get_notification_manager()

    async def event_generator():
        last_sent: Optional[int] = None
        events_sent = 0
        try:
            # 首帧立即推当前值
            last_sent = manager.get_unread_count(user_id)
            events_sent += 1
            yield f"data: {json.dumps({'type': 'unread', 'count': last_sent})}\n\n"
            while max_events is None or events_sent < max_events:
                await asyncio.sleep(interval)
                count = manager.get_unread_count(user_id)
                if count != last_sent:
                    last_sent = count
                    events_sent += 1
                    yield f"data: {json.dumps({'type': 'unread', 'count': count})}\n\n"
                else:
                    yield ": keep-alive\n\n"
        except asyncio.CancelledError:
            # 客户端断开由 StreamingResponse 取消生成器收尾
            raise
        except Exception as e:  # 管理器异常不静默——推 error 帧后收尾
            logger.exception("notification stream error: %s", e)
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


def _mark_read_impl(request: Request, notification_id: str, current_user: Dict[str, Any]):
    request_id = _get_request_id(request)
    user_id = current_user["user_id"]
    manager = get_notification_manager()
    success = manager.mark_as_read(notification_id, user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification '{notification_id}' not found or access denied",
        )
    return {
        "code": 0,
        "message": f"Notification '{notification_id}' marked as read",
        "data": {"notification_id": notification_id},
        "request_id": request_id,
    }


@router.post("/{notification_id}/read")
async def mark_as_read_post(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_default),
    notification_id: str = Path(..., description="通知ID"),
):
    """标记通知已读（POST，前端契约）"""
    try:
        return _mark_read_impl(request, notification_id, current_user)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to mark notification as read: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to mark notification as read: {str(e)}"
        )


@router.put("/{notification_id}/read")
async def mark_as_read(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_default),
    notification_id: str = Path(..., description="通知ID"),
):
    """标记通知已读（PUT 兼容保留）"""
    try:
        return _mark_read_impl(request, notification_id, current_user)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to mark notification as read: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to mark notification as read: {str(e)}"
        )


def _mark_all_read_impl(request: Request, current_user: Dict[str, Any]):
    request_id = _get_request_id(request)
    user_id = current_user["user_id"]
    count = get_notification_manager().mark_all_as_read(user_id)
    return {
        "code": 0,
        "message": f"Marked {count} notifications as read",
        "data": {"marked_count": count},
        "request_id": request_id,
    }


@router.post("/mark-all-read")
async def mark_all_as_read_post(request: Request, current_user: Dict[str, Any] = Depends(get_current_user_or_default)):
    """标记所有通知已读（POST，前端契约）"""
    try:
        return _mark_all_read_impl(request, current_user)
    except Exception as e:
        logger.exception("Failed to mark all notifications as read: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark all notifications as read: {str(e)}",
        )


@router.put("/read-all")
async def mark_all_as_read(request: Request, current_user: Dict[str, Any] = Depends(get_current_user_or_default)):
    """标记所有通知已读（PUT /read-all 兼容保留）"""
    try:
        return _mark_all_read_impl(request, current_user)
    except Exception as e:
        logger.exception("Failed to mark all notifications as read: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark all notifications as read: {str(e)}",
        )


@router.delete("/{notification_id}")
async def delete_notification(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_default),
    notification_id: str = Path(..., description="通知ID"),
):
    """删除通知"""
    request_id = _get_request_id(request)

    try:
        user_id = current_user["user_id"]
        manager = get_notification_manager()
        success = manager.delete_notification(notification_id, user_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Notification '{notification_id}' not found or access denied",
            )

        return {
            "code": 0,
            "message": f"Notification '{notification_id}' deleted",
            "data": {"notification_id": notification_id},
            "request_id": request_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to delete notification: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete notification: {str(e)}"
        )


@router.get("/push-statistics")
async def get_push_statistics(request: Request, current_user: Dict[str, Any] = Depends(get_current_user_or_default)):
    """获取推送统计"""
    request_id = _get_request_id(request)

    try:
        # 获取当前用户（从依赖注入）
        # 这里简化处理，实际应该从请求中获取用户ID
        user_id = current_user["user_id"]

        # 获取通知管理器
        manager = get_notification_manager()

        # 获取推送统计
        statistics = manager.get_push_statistics(user_id)

        return {
            "code": 0,
            "message": "success",
            "data": statistics,
            "request_id": request_id,
        }

    except Exception as e:
        logger.exception("Failed to get push statistics: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to get push statistics: {str(e)}"
        )
