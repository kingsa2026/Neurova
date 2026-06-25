"""
Neurova 安全体系 2.0

提供完整的安全防护：
- 工具守卫 (Tool Guard)
- 技能扫描器 (Skill Scanner)
- 认证系统 (Auth System)
- 认知安全 (Cognitive Security)

与 Neurova 的认知增强特性深度集成。
"""

import logging

from neurova.core.logger import get_logger
from typing import TYPE_CHECKING

_logger = get_logger(__name__)

try:
    from neurova.security.api_keys import APIKey
except ImportError as _e:
    _logger.debug("APIKey 未可用: %s", _e)
    APIKey = None

try:
    from neurova.security.auth_system import ApprovalMode
except ImportError as _e:
    _logger.debug("ApprovalMode 未可用: %s", _e)
    ApprovalMode = None

try:
    from neurova.security.audit_logger import AuditLog
except ImportError as _e:
    _logger.debug("AuditLog 未可用: %s", _e)
    AuditLog = None

try:
    from neurova.security.rbac import Permission, Role
except ImportError as _e:
    _logger.debug("Permission/Role 未可用: %s", _e)
    Permission = None
    Role = None

if TYPE_CHECKING:
    pass


def get_logger(name: str = "security"):
    """获取安全模块日志记录器"""
    import logging

    return logging.getLogger(f"neurova.security.{name}" if name != "security" else name)


__all__ = [
    "APIKey",
    "ApprovalMode",
    "AuditLog",
    "Permission",
    "Role",
    "get_logger",
]
