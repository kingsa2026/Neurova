"""
通知中心模块 - Notifications Module

提供用户级通知管理和负一屏推送集成功能。

核心组件：
- NegativeScreenConfig: 负一屏配置数据结构
- NegativeScreenConfigManager: 用户级配置管理器
- NegativeScreenPusher: 负一屏推送执行器
- NotificationManager: 通知管理器（集成负一屏推送）
"""

from .negative_screen import (
    NegativeScreenConfig,
    NegativeScreenConfigManager,
    NegativeScreenPusher,
    PushResult,
)
from .manager import NotificationManager

__all__ = [
    "NegativeScreenConfig",
    "NegativeScreenConfigManager",
    "NegativeScreenPusher",
    "PushResult",
    "NotificationManager",
]
