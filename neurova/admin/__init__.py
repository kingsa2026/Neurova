"""
Neurova 管理员服务

功能:
1. 用户管理（创建、删除、备份）
2. 系统配置
3. 数据清理
"""


from neurova.admin.admin_service import AdminService

from neurova.admin.resource_quota_manager import ResourceQuotaManager, ResourceUsage

# 这三名现役都是直取子模块（`from neurova.admin.admin_service import ...`），
# 但 `admin_service.py:85-89` 记着一条真事故：配额 stub 时代码"按 `neurova.admin.__init__`
# 的导出调真 API"拿到 AttributeError。这层导出因此是**明写的对外契约**，不是顺手抄的第二本词汇表；
# 要不要收掉＝档案 facade-reexport-triage 票三那一次裁定，本批只把契约写出来。
__all__ = [
    "AdminService",
    "ResourceQuotaManager",
    "ResourceUsage",
]
