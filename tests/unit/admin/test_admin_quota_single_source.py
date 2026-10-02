"""红灯①：AdminService 的配额账本必须与全仓唯一配额单例同源。

现状：`admin_service.py` 内自带一个同名 stub `ResourceQuotaManager`（只有
check/record/get_usage 三个方法，无 increment_*），AdminService 装的是它。
于是「桌面端记账」与「neurflow 记账」落在两本互不相干的账本上，
且按 `neurova/admin/__init__.py` 的导出去调 `increment_llm_call` 得到
AttributeError 而不是额度拦截。
"""


def testAdminServiceQuotaIsTheRepoWideSingleton(tmp_path, monkeypatch):
    import neurova.admin.resource_quota_manager as rqm
    monkeypatch.setattr(rqm, "_DEFAULT_DIR", str(tmp_path / "resource_quota"))
    rqm.reset_resource_quota_manager()
    try:
        from neurova.admin.admin_service import AdminService
        svc = AdminService(str(tmp_path / "admin"))
        assert svc.quotaManager is rqm.get_resource_quota_manager()
    finally:
        rqm.reset_resource_quota_manager()


def testAdminServiceQuotaSupportsIncrementApi(tmp_path, monkeypatch):
    """按 admin 包导出调用真 API 不得 AttributeError。"""
    import neurova.admin.resource_quota_manager as rqm
    monkeypatch.setattr(rqm, "_DEFAULT_DIR", str(tmp_path / "resource_quota"))
    rqm.reset_resource_quota_manager()
    try:
        from neurova.admin.admin_service import AdminService
        svc = AdminService(str(tmp_path / "admin"))
        user = svc.create_user(username="u1", email="u1@x.com")
        svc.quotaManager.increment_llm_call(user["id"])
        assert svc.quotaManager.get_usage(user["id"]).llm_call_count == 1
    finally:
        rqm.reset_resource_quota_manager()


def testAdminServiceModuleHasNoSecondQuotaClass():
    """单一事实源：admin_service 不得再定义 ResourceQuotaManager。"""
    import neurova.admin.admin_service as admin_service

    assert not hasattr(admin_service, "ResourceQuotaManager"), (
        "admin_service 内不得再自带同名配额类——第二份定义必须收口到 "
        "neurova.admin.resource_quota_manager"
    )
