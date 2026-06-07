"""
跨渠道会话同步系统

提供统一的会话管理，支持多渠道实时同步对话。

核心组件：
- SessionSyncManager: 会话同步管理器
- UnifiedSession: 统一会话数据结构
- SessionEvent: 会话事件
- ChannelConnection: 渠道连接

使用方式：
    from neurova.sync import get_session_sync_manager
    
    manager = get_session_sync_manager()
    
    # 创建会话
    session = manager.create_session(user_id="user_1", agent_id="agent_1")
    
    # 注册渠道
    manager.register_channel(session.session_id, "web", send_callback)
    
    # 广播事件
    await manager.broadcast_event(session.session_id, event)
"""

from .session_sync_manager import (
    SessionSyncManager,
    UnifiedSession,
    SessionEvent,
    ChannelConnection,
    EventType,
    get_session_sync_manager,
    reset_session_sync_manager,
)

__all__ = [
    "SessionSyncManager",
    "UnifiedSession",
    "SessionEvent",
    "ChannelConnection",
    "EventType",
    "get_session_sync_manager",
    "reset_session_sync_manager",
]
