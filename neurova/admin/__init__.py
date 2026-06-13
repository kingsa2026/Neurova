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
    _logger.debug("AdminService 未可用: %s", _e)
    AdminService = None

try:
    from neurova.admin.resource_quota_manager import ResourceQuotaManager, ResourceUsage
except ImportError as _e:
    _logger.debug("ResourceQuotaManager 未可用: %s", _e)
    ResourceQuotaManager = None
    ResourceUsage = None

# admin imports
try:
    pass
except ImportError as _e:
    _logger.debug("admin.admin_service 模块未可用: %s", _e)

try:
    pass
except ImportError as _e:
    _logger.debug("admin.resource_quota_manager 模块未可用: %s", _e)
