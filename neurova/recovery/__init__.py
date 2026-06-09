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
    _logger.debug(f"ShutdownGuard 未可用: {_e}")
    ShutdownGuard = None

# recovery imports
try:
    import neurova.recovery.shutdown_guard
except ImportError as _e:
    _logger.debug(f"recovery.shutdown_guard 模块未可用: {_e}")