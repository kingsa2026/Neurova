"""
Neurova 恢复系统 — 记忆写入安全兜底

模块:
    ShutdownGuard: 管理 sentinel 标记、优雅关闭、崩溃恢复
"""

import logging

_logger = logging.getLogger(__name__)

try:
    from neurova.recovery.shutdown_guard import ShutdownGuard
except ImportError as _e:
    _logger.debug("ShutdownGuard 未可用: %s", _e)
    ShutdownGuard = None

# recovery imports
try:
    pass
except ImportError as _e:
    _logger.debug("recovery.shutdown_guard 模块未可用: %s", _e)
