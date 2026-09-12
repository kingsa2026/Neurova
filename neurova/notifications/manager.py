"""
通知管理器 - Notification Manager

增强功能：
1. 集成负一屏推送
2. 用户级配置管理
3. 任务完成自动推送
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import json
import os
import pathlib
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .negative_screen import (
    NegativeScreenConfigManager,
    NegativeScreenPusher,
    PushResult,
)

logger = get_logger(__name__)

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

    # 负一屏推送状态
    negative_screen_pushed: bool = False
    negative_screen_push_time: Optional[float] = None
    negative_screen_task_id: Optional[str] = None


class NotificationManager:
    """
    通知管理器（JSON 文件持久化 + 负一屏推送集成）

    功能：
    1. 管理用户通知（落盘 data/notifications.json，重启不丢）
    2. 任务完成时自动推送到负一屏
    3. 追踪推送状态（negative_screen_* 字段随通知持久化）

    2026-09-12 双实现收口：本类为全站唯一通知存储；端点
    neurova/api/endpoints/notifications.py 直接复用本类（曾存在的端点内
    平行 JSON 版已删除——approval 镜像与铃铛分读两单例导致审批通知永不可见）。
    """

    def __init__(
        self,
        negative_screen_config_manager: NegativeScreenConfigManager = None,
        negative_screen_pusher: NegativeScreenPusher = None,
        storage_path: Optional[str] = None,
    ):
        """
        初始化通知管理器

        Args:
            negative_screen_config_manager: 负一屏配置管理器
            negative_screen_pusher: 负一屏推送器
            storage_path: 通知持久化文件路径（默认 NEUROVA_NOTIFICATIONS_PATH 或 data/notifications.json）
        """
        self._storage_path = pathlib.Path(
            storage_path or os.environ.get("NEUROVA_NOTIFICATIONS_PATH") or _DEFAULT_STORAGE
        )
        self._notifications: Dict[str, Notification] = {}
        self._user_notifications: Dict[str, List[str]] = {}  # user_id -> notification_ids
        self._lock = threading.RLock()

        # 负一屏集成
        self._negative_screen_config_manager = negative_screen_config_manager
        self._negative_screen_pusher = negative_screen_pusher or NegativeScreenPusher()

        # 推送回调
        self._push_callbacks: List[Callable[[str, PushResult], None]] = []

        self._load()
        logger.info("NotificationManager 初始化完成（持久化: %s）", self._storage_path)

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
                    negative_screen_pushed=bool(item.get("negative_screen_pushed")),
                    negative_screen_push_time=item.get("negative_screen_push_time"),
                    negative_screen_task_id=item.get("negative_screen_task_id"),
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
                        "negative_screen_pushed": n.negative_screen_pushed,
                        "negative_screen_push_time": n.negative_screen_push_time,
                        "negative_screen_task_id": n.negative_screen_task_id,
                    }
                    for nid, n in self._notifications.items()
                },
                "index": self._user_notifications,
            }
            tmp = self._storage_path.with_name(self._storage_path.name + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._storage_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save notifications to %s: %s", self._storage_path, exc)

    def add_notification(
        self,
        user_id: str,
        title: str,
        message: str,
        notification_type: str = "info",
        data: Optional[Dict[str, Any]] = None,
        push_to_negative_screen: bool = False,
    ) -> Notification:
        """
        添加通知

        Args:
            user_id: 用户ID
            title: 通知标题
            message: 通知内容
            notification_type: 通知类型（info, task_completed, warning, error）
            data: 附加数据
            push_to_negative_screen: 是否推送到负一屏

        Returns:
            通知对象
        """
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

            # 根据类型决定是否推送到负一屏
            should_push = push_to_negative_screen or notification_type == "task_completed"

            if should_push and self._negative_screen_config_manager:
                # 异步推送（不阻塞）
                self._schedule_negative_screen_push(user_id, notification)

            self._save()
            logger.info("添加通知: %s, user=%s, type=%s", notification_id, user_id, notification_type)
            return notification

    def _schedule_negative_screen_push(
        self,
        user_id: str,
        notification: Notification,
    ) -> None:
        """调度负一屏推送"""
        try:
            # 获取用户配置
            config = self._negative_screen_config_manager.get_config(user_id)

            if not config or not config.enabled or not config.auth_code:
                logger.debug("用户 %s 未配置负一屏推送", user_id)
                return

            # 准备推送数据
            task_name = notification.title
            task_content = notification.data.get("task_content", notification.message)
            task_result = notification.data.get("task_result", "任务已完成")

            # 使用线程异步推送
            def push_async():
                try:
                    import asyncio

                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    result = loop.run_until_complete(
                        self._negative_screen_pusher.push_task(
                            config=config,
                            task_name=task_name,
                            task_content=task_content,
                            task_result=task_result,
                        )
                    )

                    loop.close()

                    # 更新通知状态
                    with self._lock:
                        notification.negative_screen_pushed = result.success
                        notification.negative_screen_push_time = time.time()
                        notification.negative_screen_task_id = result.task_id
                        self._save()

                    # 触发回调
                    for callback in self._push_callbacks:
                        try:
                            callback(user_id, result)
                        except Exception as e:
                            logger.error("推送回调执行失败: %s", e)

                    if result.success:
                        logger.info("负一屏推送成功: %s", notification.notification_id)
                    else:
                        logger.warning("负一屏推送失败: %s, error=%s", notification.notification_id, result.error)

                except Exception as e:
                    logger.error("负一屏推送异常: %s, error=%s", notification.notification_id, e)

            thread = threading.Thread(target=push_async, daemon=True)
            thread.start()

        except Exception as e:
            logger.error("调度负一屏推送失败: %s", e)

    def add_push_callback(self, callback: Callable[[str, PushResult], None]) -> None:
        """添加推送回调"""
        self._push_callbacks.append(callback)

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
                        if notification.negative_screen_pushed:
                            pushed += 1
                        else:
                            failed += 1

            return {
                "total_task_notifications": total,
                "pushed_to_negative_screen": pushed,
                "push_failed": failed,
                "push_rate": pushed / total if total > 0 else 0.0,
            }


# ─── 全局实例管理 ────────────────────────────────────────────────────────────


_notification_manager: Optional[NotificationManager] = None
_manager_lock = threading.Lock()


def get_notification_manager(
    negative_screen_config_manager: NegativeScreenConfigManager = None,
) -> NotificationManager:
    """获取全局通知管理器单例

    2026-09-12 负一屏残留修复：缺省注入 NegativeScreenConfigManager()
    （与负一屏设置页同源目录 data/negative_screen）——此前生产从不传参，
    _schedule_negative_screen_push 永不触发，推送链路整体休眠。
    构造失败降级为无配置管理器（铃铛不受影响）并记日志。
    """
    global _notification_manager
    if _notification_manager is None:
        with _manager_lock:
            if _notification_manager is None:
                if negative_screen_config_manager is None:
                    try:
                        negative_screen_config_manager = NegativeScreenConfigManager()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("负一屏配置管理器初始化失败，推送功能降级: %s", exc)
                _notification_manager = NotificationManager(
                    negative_screen_config_manager=negative_screen_config_manager,
                )
    return _notification_manager


def reset_notification_manager() -> None:
    """重置全局通知管理器（用于测试）"""
    global _notification_manager
    with _manager_lock:
        _notification_manager = None
