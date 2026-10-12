# -*- coding: utf-8 -*-
"""授权存储的落盘与审计纪律（§6-155 立的规则，§6-157 换掉词汇后原样保留）。

本文件只管**存储这一层**的四条纪律，词汇与两类面的口径在
`tests/unit/plugins/test_pluginPermissionSingleSource.py`，挂载门与调用面仲裁在
`tests/unit/plugins/test_pluginRoutesAreMounted.py`，事件面强制点在
`tests/unit/test_base_plugin.py`——同一规则只在一处钉（教义第 6 条）。
§6-157 收口时本文件从 21 格降到现在这些：删掉的 4 格档位模型格（`PERMISSION_MODEL`/`PermissionTier`
随「甲 · 彻底合一」退役，替代判据在 `test_pluginPermissionSingleSource.py`）与 4 格事件总线格
（与 `test_base_plugin.py` 同题，留在那一档更贴生产接缝）——**规则一条没少，只是不再两处钉**。

四条纪律：
1. 授予只允许授予清单**声明过**的项（防"先授予、后声明"这条越权路径）；
2. 授予要落盘且能被新实例读回——它是人的决定，不是内存字典（内存字典意味着每次重启
   管理面重做一遍，人于是闭眼点）；
3. 审计写不进去 ⇒ 变更回滚（不留"改了却没记"的半态）；
4. 文件坏了 ⇒ 响亮地拒、不覆写；读侧一律朝安全侧失败（读不出＝没有授权）。
"""

from __future__ import annotations

import json

import pytest

from neurova.plugins.plugin_errors import PluginError
from neurova.plugins.plugin_permissions import PluginPermissionStore
from neurova.plugins.plugin_manifest import PluginFrameworkSurface

#: 一个能力键（来自 skills 那份单点）＋一个框架中介面（插件独有），两类各测一遍
CAPABILITY = "network"
SURFACE = PluginFrameworkSurface.READ_EVENTS.value


@pytest.fixture()
def store(tmp_path):
    declared = {"probe": [CAPABILITY, SURFACE], "wide": [CAPABILITY, "file", "model"]}
    return PluginPermissionStore(path=str(tmp_path / "permissions.json"),
                                 declaredProvider=lambda pid: list(declared.get(pid, [])))


class TestGrantFollowsDeclaration:
    def test_grantBeforeAnythingIsNotGranted(self, store):
        assert store.isGranted("probe", CAPABILITY) is False
        assert store.grantedFor("probe") == []

    def test_grantingAnUndeclaredItemIsRefused(self, store):
        with pytest.raises(PluginError) as caught:
            store.grant("probe", "file", grantedBy="admin-1")

        assert caught.value.reason == "permission_not_declared"
        assert store.grantedFor("probe") == [], "拒了却仍记了一笔：读数与事实不符"

    def test_granting_an_item_outside_both_vocabularies_is_refused(self, store):
        with pytest.raises(PluginError) as caught:
            store.grant("probe", "read:everything", grantedBy="admin-1")

        assert caught.value.reason == "unknown_permission"

    def test_declared_grant_succeeds_and_is_readable(self, store):
        record = store.grant("probe", CAPABILITY, grantedBy="admin-1")

        assert store.isGranted("probe", CAPABILITY)
        assert record["granted_by"] == "admin-1"
        assert record["kind"] == "capability"

    def test_pending_is_declared_minus_granted(self, store):
        assert set(store.pendingFor("wide")) == {CAPABILITY, "file", "model"}

        store.grant("wide", CAPABILITY, grantedBy="admin-1")

        assert set(store.pendingFor("wide")) == {"file", "model"}, (
            "确认后仍列在 pending——面板永远显示「待确认」，人便不再信它")

    def test_surface_and_capability_records_are_distinguishable(self, store):
        store.grant("probe", CAPABILITY, grantedBy="admin-1")
        surfaceRecord = store.grant("probe", SURFACE, grantedBy="admin-1")

        assert surfaceRecord["kind"] == "surface", (
            "两类面必须在记录里可区分——否则面板与审计都读不出「这一项由谁去拦」")


class TestGrantsLandOnDisk:
    def testAFreshStoreReadsBackTheGrants(self, tmp_path, store):
        store.grant("probe", CAPABILITY, grantedBy="admin-1")

        reopened = PluginPermissionStore(path=str(tmp_path / "permissions.json"),
                                         declaredProvider=lambda pid: [CAPABILITY])

        assert reopened.isGranted("probe", CAPABILITY), "授予只在内存里＝重启即失效，面板却显示已确认"

    def testRevokeRemovesItFromDiskToo(self, tmp_path, store):
        store.grant("probe", CAPABILITY, grantedBy="admin-1")
        store.revoke("probe", CAPABILITY, grantedBy="admin-1")

        reopened = PluginPermissionStore(path=str(tmp_path / "permissions.json"),
                                         declaredProvider=lambda pid: [CAPABILITY])

        assert not reopened.isGranted("probe", CAPABILITY)
        assert set(reopened.pendingFor("probe")) == {CAPABILITY}

    def testRevokeOfSomethingNotGrantedIsNamedNotSilent(self, store):
        with pytest.raises(PluginError) as caught:
            store.revoke("probe", CAPABILITY, grantedBy="admin-1")

        assert caught.value.reason == "not_granted", (
            "撤销一条不存在的授予却报成功——审计里会留下一条从未生效的撤销记录")

    def testOrphanedShowsGrantsTheManifestStoppedDeclaring(self, store):
        store.grant("probe", CAPABILITY, grantedBy="admin-1")

        assert store.orphanedFor("probe") == []
        shrunk = PluginPermissionStore(path=store.path, declaredProvider=lambda pid: [SURFACE])
        assert set(shrunk.orphanedFor("probe")) == {CAPABILITY}, (
            "清单改过而授权没跟——这一列不显示，面板就看不出还留着旧授权")

    def testDropPluginClearsGrantsAndMountTogether(self, store):
        store.grant("probe", CAPABILITY, grantedBy="admin-1")
        store.authorizeMount("probe", grantedBy="admin-1", routes=["/api/v1/plugin-api/probe/x"])

        assert store.dropPlugin("probe", grantedBy="admin-1") == 1
        assert store.grantedFor("probe") == []
        assert store.mountAuthorized("probe") is False, (
            "孤儿授权：同名插件重装即白捡上次的能力与上次放开的 HTTP 面")


class TestCorruptStoreIsLoudNotSilent:
    def testMutationsAreRefusedAndTheFileIsLeftAlone(self, tmp_path):
        path = tmp_path / "permissions.json"
        path.write_text("{not json", encoding="utf-8")
        reopened = PluginPermissionStore(path=str(path), declaredProvider=lambda pid: [CAPABILITY])

        with pytest.raises(PluginError) as caught:
            reopened.grant("probe", CAPABILITY, grantedBy="admin-1")

        assert caught.value.reason == "grants_store_corrupt"
        assert path.read_text(encoding="utf-8") == "{not json", (
            "把坏文件覆写掉＝销毁「当初确认过什么」的唯一证据")

    def testReadsFailClosedAndSnapshotSaysItIsBroken(self, tmp_path):
        """失败方向也要钉住：坏文件＝谁都没被授予（安全侧），且读数面**看得见**坏了。"""
        path = tmp_path / "permissions.json"
        path.write_text("{not json", encoding="utf-8")
        reopened = PluginPermissionStore(path=str(path), declaredProvider=lambda pid: [CAPABILITY])

        assert reopened.isGranted("probe", CAPABILITY) is False
        assert reopened.grantedFor("probe") == []
        assert reopened.snapshot()["corrupt"] is True, (
            "读数面不暴露「坏了」——面板会显示一张空授权表，看上去像「还没人确认过」")


class TestAuditIsNotSkippable:
    def testGrantIsReadableBackFromTheExistingAuditSurface(self, store, tmp_path, monkeypatch):
        """审计写进既有 `AuditLogger` 的表（不新造平行体系，教义第 6 条），
        判据按真产物读回——替身"被调用过一次"而库里没这条，等于没记。"""
        from neurova.security.audit_logger import AuditEventType, AuditLogEntry, AuditLogger

        auditDb = str(tmp_path / "audit.db")
        logger = AuditLogger(db_path=auditDb)
        saved = logger._db_path
        logger._db_path = auditDb
        if saved != auditDb:
            # 复用中的单例 `__init__` 会早退（`_initialized` 已 True），新落点的表没人建；
            # 不补这一下，INSERT 失败会被"审计写不进即回滚"那条规则读成本文件的红。
            logger._init_db()
        monkeypatch.setattr(
            "neurova.plugins.plugin_permissions.log_audit",
            lambda event_type, severity, **kw: logger.log(
                AuditLogEntry(event_type=event_type, severity=severity, **kw)))
        try:
            store.grant("probe", CAPABILITY, grantedBy="admin-1")

            entries = [e for e in logger.query(event_type=AuditEventType.PERMISSION_CHANGE)
                       if e.resource_id == "probe"]
            assert len(entries) == 1, "授予没进审计：事后无从知道是谁确认的（读到 %s 条）" % len(entries)
            assert entries[0].user_id == "admin-1"
            assert entries[0].action == "plugin_permission_grant"
            assert CAPABILITY in json.dumps(entries[0].details, ensure_ascii=False)
        finally:
            logger._db_path = saved

    def testGrantDoesNotTakeEffectIfAuditWriteFails(self, store, monkeypatch):
        import neurova.plugins.plugin_permissions as mod

        monkeypatch.setattr(mod, "log_audit", lambda *a, **kw: False)

        with pytest.raises(PluginError) as caught:
            store.grant("probe", CAPABILITY, grantedBy="admin-1")

        assert caught.value.reason == "audit_write_failed"
        assert not store.isGranted("probe", CAPABILITY)
        reopened = PluginPermissionStore(path=store.path, declaredProvider=lambda pid: [CAPABILITY])
        assert not reopened.isGranted("probe", CAPABILITY), (
            "内存回滚了、盘上留着——重启后这条没有留痕的授予又活了")

    def testMountAuthorizationFollowsTheSameAuditRule(self, store, monkeypatch):
        import neurova.plugins.plugin_permissions as mod

        store.grant("probe", CAPABILITY, grantedBy="admin-1")
        monkeypatch.setattr(mod, "log_audit", lambda *a, **kw: True)
        store.authorizeMount("probe", grantedBy="admin-1", routes=["/x"])
        assert store.mountAuthorized("probe") is True

        monkeypatch.setattr(mod, "log_audit", lambda *a, **kw: False)
        with pytest.raises(PluginError) as caught:
            store.authorizeMount("probe", grantedBy="admin-1", routes=["/y"])
        assert caught.value.reason == "audit_write_failed"
        assert store.snapshot()["mounts"]["probe"]["routes"] == ["/x"], (
            "挂载授权的审计写失败却把路由列表改掉了：读出来的 HTTP 面与实际放行的不是一份")
