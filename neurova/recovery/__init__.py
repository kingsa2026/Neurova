"""
Neurova 恢复系统 — 记忆写入安全兜底

模块:
    ShutdownGuard: 管理 sentinel 标记、优雅关闭、崩溃恢复
"""

from neurova.core.logger import get_logger
_logger = get_logger(__name__)

try:
    from neurova.recovery.shutdown_guard import ShutdownGuard
except ImportError as _e:
    _logger.debug("ShutdownGuard 未可用: %s", _e)
    ShutdownGuard = None
