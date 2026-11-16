"""
Neurova 认证模块:

整合用户模型、密码加密、Token 管理
提供统一的认证接口
"""

# （S7 死码退役批）enhanced_user_model 已按 P1-20 整体退役（生产零消费，
# 与 user_model.UserModel 构成第二套用户体系）；用户模型唯一事实源是
# neurova/auth/user_model.py::UserModel。

# FastAPI 为可选依赖
try:
    from fastapi import Path as _FastAPIPath
except ImportError:
    _FastAPIPath = None  # type: ignore[assignment]

from neurova.security.rbac import Permission

from neurova.admin.resource_quota_manager import ResourceQuotaManager

from neurova.auth.user_model import User

from neurova.auth.user_group_model import UserGroupManager

__all__ = [
    "Permission",
    "ResourceQuotaManager",
    "User",
    "UserGroupManager",
]
