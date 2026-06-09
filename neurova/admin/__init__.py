"""
Neurova 管理员服务

功能:
1. 用户管理（创建、删除、备份）
2. 系统配置
3. 数据清理
"""

import logging

_logger = logging.getLogger(__name__)

try:
    from neurova.admin.admin_service import AdminService
except ImportError as _e:
    _logger.debug(f"AdminService 未可用: {_e}")
    AdminService = None

try:
    from neurova.admin.resource_quota_manager import ResourceQuotaManager, ResourceUsage
except ImportError as _e:
    _logger.debug(f"ResourceQuotaManager 未可用: {_e}")
    ResourceQuotaManager = None
    ResourceUsage = None

# admin imports
try:
    import neurova.admin.admin_service
except ImportError as _e:
    _logger.debug(f"admin.admin_service 模块未可用: {_e}")

try:
    import neurova.admin.resource_quota_manager
except ImportError as _e:
    _logger.debug(f"admin.resource_quota_manager 模块未可用: {_e}")