"""
Neurova 认证模块:

整合用户模型、密码加密、Token 管理
提供统一的认证接口
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from neurova.auth.enhanced_user_model import EnhancedUserModel
except ImportError:
    EnhancedUserModel = None  # type: ignore[assignment,misc]

try:
    import hashlib
except ImportError:
    hashlib = None  # type: ignore[assignment]

# FastAPI 为可选依赖
try:
    from fastapi import Path as _FastAPIPath
except ImportError:
    _FastAPIPath = None  # type: ignore[assignment]

try:
    from neurova.security.rbac import Permission
except ImportError:
    Permission = None  # type: ignore[assignment,misc]

try:
    from neurova.admin.resource_quota_manager import ResourceQuotaManager
except ImportError:
    ResourceQuotaManager = None  # type: ignore[assignment,misc]

try:
    from neurova.auth.user_model import User
except ImportError:
    User = None  # type: ignore[assignment,misc]

try:
    from neurova.auth.user_group_model import UserGroupManager
except ImportError:
    UserGroupManager = None  # type: ignore[assignment,misc]

# auth imports
try:
    import neurova.auth.enhanced_user_model
    import neurova.auth.password_hasher
    import neurova.auth.user_group_model
    import neurova.auth.user_model
except ImportError as e:
    logger.debug(f"部分 auth 子模块导入失败: {e}")

__all__ = [
    "EnhancedUserModel", "Permission", "ResourceQuotaManager",
    "User", "UserGroupManager",
]
