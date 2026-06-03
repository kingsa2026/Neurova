"""
Neurova 安全体系 2.0

提供完整的安全防护：
- 工具守卫 (Tool Guard)
- 技能扫描器 (Skill Scanner)
- 认证系统 (Auth System)
- 认知安全 (Cognitive Security)

与 Neurova 的认知增强特性深度集成。
"""

from typing import TYPE_CHECKING

from neurova.security.api_keys import APIKey
from neurova.security.auth_system import ApprovalMode
from neurova.security.audit_logger import AuditLog
from neurova.security.rbac import Permission, Role

if TYPE_CHECKING:
    from neurova.auth.user_model import User
    from neurova.skills.models import Skill

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