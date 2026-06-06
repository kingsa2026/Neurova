from __future__ import annotations

"""
通知管理接口 - Notifications Endpoint

功能:
1. 获取通知列表 (GET /api/v1/notifications)
2. 标记已读 (PUT /api/v1/notifications/{id}/read)
3. 标记全部已读 (PUT /api/v1/notifications/read-all)
4. 删除通知 (DELETE /api/v1/notifications/{id})
"""

import logging
import time
import threading
import uuid
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


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
    """通知管理器（内存存储）"""
    
    def __init__(self):
        """初始化通知管理器"""
        self._notifications: Dict[str, Notification] = {}
        self._user_notifications: Dict[str, List[str]] = {}  # user_id -> notification_ids
        self._lock = threading.RLock()
    
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
            return notifications[offset:offset + limit]
    
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
                    nid for nid in self._user_notifications[user_id]
                    if nid != notification_id
                ]
            
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


# 全局通知管理器单例
_notification_manager: Optional[NotificationManager] = None
_manager_lock = threading.Lock()


def get_notification_manager() -> NotificationManager:
    """获取全局通知管理器单例"""
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


class NotificationItem(BaseModel):
    """通知条目"""
    notification_id: str
    user_id: str
    title: str
    message: str
    notification_type: str = "info"
    read: bool = False
    created_at: float = 0.0
    data: Dict[str, Any] = {}


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _convert_notification_to_item(notification: Notification) -> NotificationItem:
    """将Notification转换为API响应格式"""
    return NotificationItem(
        notification_id=notification.notification_id,
        user_id=notification.user_id,
        title=notification.title,
        message=notification.message,
        notification_type=notification.notification_type,
        read=notification.read,
        created_at=notification.created_at,
        data=notification.data,
    )


@router.get("", response_model=List[NotificationItem])
async def get_notifications(
    request: Request,
    read: Optional[bool] = Query(default=None, description="已读状态筛选"),
    notification_type: Optional[str] = Query(default=None, description="通知类型筛选"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
):
    """获取通知列表"""
    try:
        # 获取当前用户（从依赖注入）
        # 这里简化处理，实际应该从请求中获取用户ID
        user_id = "default_user"  # TODO: 从认证中获取实际用户ID
        
        # 获取通知管理器
        manager = get_notification_manager()
        
        # 获取通知列表
        notifications = manager.get_user_notifications(
            user_id=user_id,
            read=read,
            notification_type=notification_type,
            limit=limit,
            offset=offset,
        )
        
        # 转换为API格式
        return [_convert_notification_to_item(n) for n in notifications]
        
    except Exception as e:
        logger.exception(f"Failed to get notifications: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get notifications: {str(e)}"
        )


@router.get("/unread-count")
async def get_unread_count(request: Request):
    """获取未读通知数量"""
    try:
        # 获取当前用户（从依赖注入）
        # 这里简化处理，实际应该从请求中获取用户ID
        user_id = "default_user"  # TODO: 从认证中获取实际用户ID
        
        # 获取通知管理器
        manager = get_notification_manager()
        
        # 获取未读数量
        unread_count = manager.get_unread_count(user_id)
        
        return {
            "code": 0,
            "message": "success",
            "data": {"unread_count": unread_count},
        }
        
    except Exception as e:
        logger.exception(f"Failed to get unread count: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get unread count: {str(e)}"
        )


@router.put("/{notification_id}/read")
async def mark_as_read(
    request: Request,
    notification_id: str = Path(..., description="通知ID"),
):
    """标记通知已读"""
    request_id = _get_request_id(request)
    
    try:
        # 获取当前用户（从依赖注入）
        # 这里简化处理，实际应该从请求中获取用户ID
        user_id = "default_user"  # TODO: 从认证中获取实际用户ID
        
        # 获取通知管理器
        manager = get_notification_manager()
        
        # 标记已读
        success = manager.mark_as_read(notification_id, user_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Notification '{notification_id}' not found or access denied"
            )
        
        return {
            "code": 0,
            "message": f"Notification '{notification_id}' marked as read",
            "data": {"notification_id": notification_id},
            "request_id": request_id,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to mark notification as read: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark notification as read: {str(e)}"
        )


@router.put("/read-all")
async def mark_all_as_read(request: Request):
    """标记所有通知已读"""
    request_id = _get_request_id(request)
    
    try:
        # 获取当前用户（从依赖注入）
        # 这里简化处理，实际应该从请求中获取用户ID
        user_id = "default_user"  # TODO: 从认证中获取实际用户ID
        
        # 获取通知管理器
        manager = get_notification_manager()
        
        # 标记全部已读
        count = manager.mark_all_as_read(user_id)
        
        return {
            "code": 0,
            "message": f"Marked {count} notifications as read",
            "data": {"marked_count": count},
            "request_id": request_id,
        }
        
    except Exception as e:
        logger.exception(f"Failed to mark all notifications as read: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark all notifications as read: {str(e)}"
        )


@router.delete("/{notification_id}")
async def delete_notification(
    request: Request,
    notification_id: str = Path(..., description="通知ID"),
):
    """删除通知"""
    request_id = _get_request_id(request)
    
    try:
        # 获取当前用户（从依赖注入）
        # 这里简化处理，实际应该从请求中获取用户ID
        user_id = "default_user"  # TODO: 从认证中获取实际用户ID
        
        # 获取通知管理器
        manager = get_notification_manager()
        
        # 删除通知
        success = manager.delete_notification(notification_id, user_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Notification '{notification_id}' not found or access denied"
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
        logger.exception(f"Failed to delete notification: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete notification: {str(e)}"
        )
