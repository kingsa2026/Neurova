"""
Neurova 安全体系 2.0

提供完整的安全防护：
- 工具守卫 (Tool Guard)
- 技能扫描器 (Skill Scanner)
- 认知安全 (Cognitive Security)

与 Neurova 的认知增强特性深度集成。

注：用户认证走 neurova.api.auth 与 neurova.auth.password_hasher（bcrypt），
本包不再提供认证组件（S-07 死代码 security/auth_system.py 已删除）。
"""

from neurova.core.logger import get_logger

try:
    from neurova.security.audit_logger import AuditLog
except ImportError as _e:
    AuditLog = None

try:
    from neurova.security.rbac import Permission, Role
except ImportError as _e:
    Permission = None
    Role = None


def get_logger(name: str = "security"):
    """获取安全模块日志记录器"""
    import logging

    return logging.getLogger(f"neurova.security.{name}" if name != "security" else name)


__all__ = [
    "AuditLog",
    "Permission",
    "Role",
    "get_logger",
]
