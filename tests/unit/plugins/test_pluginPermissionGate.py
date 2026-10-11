# -*- coding: utf-8 -*-
"""插件权限必须逐插件、逐项由人确认后才能生效（用户 2026-10-11 裁「做插件体系并接线」，边界「含下载与安装面」，台账 §6-155）。

P1 只接通了动态装载，并留下一句诚实声明：装载与「插件可注册 HTTP 路由」是两次授权。
本文件把那**第二次授权**做成真的：8 项 `PluginPermission` 逐项有归属、有档位、有落点，
未确认即拒绝，且拒绝要能被调用方读出成因。

## 8 项枚举的逐插件确认口径（本批唯一事实源 = `plugin_permissions.PERMISSION_MODEL`）

档位三态，按「框架有没有真实中介点」分，不按「听起来危不危险」分：

| 权限 | 档位 | 框架中介点 | 未授予时 |
|------|------|-----------|---------|
| `read:events` | framework_enforced | `BasePlugin.subscribe/unsubscribe` → 事件总线 | 当场拒（`permission_not_granted`） |
| `emit:events` | framework_enforced | `BasePlugin.publish_event` → 事件总线 | 当场拒 |
| `http:request` | disclosed_only | 无：插件自己 import httpx/requests 就发得出请求 | 授予＝披露并经人签字，不是隔离 |
| `read:files` / `write:files` | disclosed_only | 同上（装载即进程内任意代码执行） | 同上 |
| `network:access` | disclosed_only | 同上 | 同上 |
| `execute:commands` | never_grantable | 本批不开放授予 | 声明它的插件**永远挂不上路由** |
| `admin` | never_grantable | 本批不开放授予 | 同上 |

`disclosed_only` 写成 disclosed_only 而不是假装 enforced，是本批最重要的一条诚实要求：
动态装载本身就把整个进程的权限给了插件，任何「权限门＝沙箱」的说法都是假的
（`docs/01-architecture/plugin-architecture-design.md` 现有「路径沙箱」表述同批改名实）。
`disclosed_only` 仍有两个真实效力：① 聚合挂载规则要求「声明 ⊆ 已确认」，声明未确认就挂不上路由；
② 每一次授予/撤销都进既有审计面（`log_audit` / `AuditEventType.PERMISSION_CHANGE`），可追溯到人。

`never_grantable` 两档的效力也是真的：`execute:commands` 与 `admin` 一旦被授予，
「声明 ⊆ 授予」就永真地做不到（本批不给授予入口），于是这类插件只能装载、不能对外开 HTTP 面。

## 判据形态

- 授予只允许授予**该插件清单里声明过**的权限（防「先授予、后声明」的越权路径）。
- 授予/撤销要落盘且能被新实例读回（不是内存字典）。
- 审计写不进去 ⇒ 授予不生效（不留「改了却没记」的半态）。
- 清单文件坏了 ⇒ 响亮地拒，不静默读成「什么都没授予」。
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from neurova.plugins.base_plugin import BasePlugin
from neurova.plugins.plugin_manifest import PluginPermission


def _permissions():
    """权限模型模块。缺失即红灯——不许 importorskip 把它变成静默跳过，
    也不许让整档因 `ModuleNotFoundError` 变成「错误」而看不出没实现（红要红在断言上）。"""
    try:
        return importlib.import_module("neurova.plugins.plugin_permissions")
    except ModuleNotFoundError as exc:
        pytest.fail("权限单点模块不存在，逐项确认没有事实源：%s" % exc)


def _writeManifest(pdir: Path, *, permissions):
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "manifest.json").write_text(
        json.dumps({"name": pdir.name, "version": "1.0.0", "required_permissions": permissions},
                   ensure_ascii=False),
        encoding="utf-8")
    return pdir


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """存储 + 声明面都指到 tmp；声明面由夹具提供，绕开全局 manager（本文件只测存储这一层）。"""
    mod = _permissions()
    declared = {}

    def declare(plugin_id, perms):
        declared[plugin_id] = list(perms)

    instance = mod.PluginPermissionStore(
        path=str(tmp_path / "permissions.json"),
        declaredProvider=lambda pid: declared.get(pid, []))
    declare("reader", ["read:events"])
    declare("shouter", ["emit:events", "http:request"])
    declare("greedy", ["execute:commands"])
    instance.declare = declare
    return instance


@pytest.fixture(autouse=True)
def _auditIntoTmp(tmp_path, monkeypatch):
    """让「授予必进审计」真的落到 SQLite，但落点是本档自己的 tmp 文件。

    `log_audit()` 绑的是**进程级 `AuditLogger` 单例**，默认落点 `~/.neurova/audit.db`
    （数据根之外的历史形态，本批不动它、只登记）。实测教训：只换 `AuditLogger._instance`
    不够——本仓测试会话里前后夹具的复位链会把旧对象换回来，第 8 档起写的记录全落进
    第 1 档那个库（判据把别人的记录读成自己的，假红），而家目录真被写进了记录。
    这里把「在用那条 logger 的落点」显式改到 tmp，并让 `log_audit` 换成绑定同一对象的
    等价薄壳（monkeypatch 逐档还原），写侧与读侧同源。
    """
    mod = _permissions()
    from neurova.security.audit_logger import AuditLogEntry, AuditLogger

    dbPath = str(tmp_path / "audit.db")
    createdHere = AuditLogger._instance is None
    logger = AuditLogger(db_path=dbPath)
    savedPath = logger._db_path
    logger._db_path = dbPath
    if savedPath != dbPath:
        # 复用中的单例 `__init__` 会早退（`_initialized` 已 True），新落点的表没人建——
        # 于是 INSERT 撞「no such table」、`log()` 返回 False，看上去像
        # 「审计写不进去 ⇒ 授予回滚」这条规则红了，其实红的是夹具自己。
        logger._init_db()

    def _write(event_type, severity, **kwargs):
        return logger.log(AuditLogEntry(event_type=event_type, severity=severity, **kwargs))

    monkeypatch.setattr(mod, "log_audit", _write)
    try:
        yield logger
    finally:
        logger._db_path = savedPath
        if createdHere:
            # 本档新建的那条不能留在进程里——它指向的文件马上被 pytest 回收，
            # 后面的用例拿着它会一路写进一个已不存在的库（同「夹具把 `_app_state` 留在身后」）。
            AuditLogger._instance = None


@pytest.fixture()
def audit(_auditIntoTmp):
    """同一份 tmp 审计面（读数只用它，不用全局 getter）。"""
    return _auditIntoTmp


class TestPermissionModelIsOneClosedTable:
    def test_modelCoversExactlyTheEnumMembers(self):
        model = _permissions().PERMISSION_MODEL
        declared = {p for p in PluginPermission}
        tabled = set(model)
        assert tabled - declared == set(), "模型里有枚举没有的权限项：两处定义漂移了（教义第 6 条）"
        assert declared - tabled == set(), (
            "有 %s 项枚举成员没进模型——没有档位就没有口径，逐项确认做不到"
            % sorted(x.value for x in (declared - tabled)))

    def test_everyMemberNamesWhatItUnlocksAndItsTier(self):
        tierEnum = _permissions().PermissionTier
        for perm, spec in _permissions().PERMISSION_MODEL.items():
            assert spec.unlocks.strip(), f"{perm.value} 没写「授予后放行什么」——确认时无从判断"
            assert isinstance(spec.tier, tierEnum), f"{perm.value} 的档位不是封闭三态之一"
            assert spec.permission is perm, f"{perm.value} 的表项自指错了"

    def test_frameworkEnforcedMembersPointAtRealCode(self):
        """`enforcedAt` 不许只写个名字——点位必须真能在生产里取到，否则「有中介点」是假的。"""
        for perm, spec in _permissions().PERMISSION_MODEL.items():
            if spec.tier is not _permissions().PermissionTier.FRAMEWORK_ENFORCED:
                continue
            module_name, _, attr = spec.enforcedAt.partition(":")
            holder = importlib.import_module(module_name)
            target = holder
            for part in attr.split("."):
                target = getattr(target, part, None)
                assert target is not None, (
                    f"{perm.value} 声称由 {spec.enforcedAt} 强制，但该路径取不到东西")

    def test_executeCommandsAndAdminAreNotGrantable(self):
        model = _permissions().PERMISSION_MODEL
        never = {p.value for p, s in model.items()
                 if s.tier is _permissions().PermissionTier.NEVER_GRANTABLE}
        assert never == {"execute:commands", "admin"}, (
            "不可授予档位必须恰是这两项；多一项就少一块能力，少一项就是给自己开了命令面")


class TestGrantRequiresDeclaration:
    def test_grantingAnUndeclaredPermissionIsRefused(self, store):
        with pytest.raises(Exception) as caught:
            store.grant("reader", "write:files", grantedBy="admin-1")

        assert getattr(caught.value, "reason", "") == "permission_not_declared", (
            "未声明的权限被授予了——「先授予后声明」就是越权入口")
        assert not store.isGranted("reader", PluginPermission.WRITE_FILES)

    def test_unknownPermissionStringIsRefused(self, store):
        with pytest.raises(Exception) as caught:
            store.grant("reader", "read:everything", grantedBy="admin-1")

        assert getattr(caught.value, "reason", "") == "unknown_permission"

    def test_neverGrantablePermissionCannotBeGrantedEvenWhenDeclared(self, store):
        with pytest.raises(Exception) as caught:
            store.grant("greedy", "execute:commands", grantedBy="admin-1")

        assert getattr(caught.value, "reason", "") == "permission_not_grantable"
        assert store.grantedFor("greedy") == [], "拒了却仍记了一笔：读数与事实不符"

    def test_declaredGrantSucceedsAndIsReadable(self, store):
        store.grant("reader", "read:events", grantedBy="admin-1")

        assert store.isGranted("reader", PluginPermission.READ_EVENTS)
        assert "read:events" in store.grantedFor("reader")

    def test_pendingIsDeclaredMinusGranted(self, store):
        assert set(store.pendingFor("shouter")) == {"emit:events", "http:request"}

        store.grant("shouter", "emit:events", grantedBy="admin-1")

        assert set(store.pendingFor("shouter")) == {"http:request"}, (
            "确认后仍列在 pending——管理面会永远显示「待确认」，人便不再信它")


class TestGrantsLandOnDisk:
    def testAFreshStoreReadsBackTheGrants(self, tmp_path, store):
        mod = _permissions()
        store.grant("reader", "read:events", grantedBy="admin-1")

        reopened = mod.PluginPermissionStore(
            path=str(tmp_path / "permissions.json"),
            declaredProvider=lambda pid: ["read:events"] if pid == "reader" else [])

        assert reopened.isGranted("reader", PluginPermission.READ_EVENTS), (
            "授予只在内存里：重启即失效，而面板还显示已确认")

    def testRevokeRemovesItFromDiskToo(self, tmp_path, store):
        mod = _permissions()
        store.grant("reader", "read:events", grantedBy="admin-1")
        store.revoke("reader", "read:events", grantedBy="admin-1")

        reopened = mod.PluginPermissionStore(
            path=str(tmp_path / "permissions.json"),
            declaredProvider=lambda pid: ["read:events"] if pid == "reader" else [])

        assert not reopened.isGranted("reader", PluginPermission.READ_EVENTS)
        assert set(reopened.pendingFor("reader")) == {"read:events"}

    def testCorruptStoreIsRefusedNotReadAsEmpty(self, tmp_path):
        """坏文件不许静默当成「谁都没被授予过」——那会把已确认的记录无声抹掉。"""
        mod = _permissions()
        path = tmp_path / "permissions.json"
        path.write_text("{not json", encoding="utf-8")

        reopened = mod.PluginPermissionStore(path=str(path), declaredProvider=lambda pid: [])

        with pytest.raises(Exception) as caught:
            reopened.grant("reader", "read:events", grantedBy="admin-1")
        assert getattr(caught.value, "reason", "") == "grants_store_corrupt"
        assert path.read_text(encoding="utf-8") == "{not json", (
            "把坏文件覆写掉＝销毁了唯一能看出「曾经确认过什么」的证据")

    def testCorruptStoreFailsClosedOnReads(self, tmp_path):
        """读侧的失败方向也要钉住：坏文件＝谁都没被授予（安全侧），而不是「全放行」也不是无声忽略。"""
        mod = _permissions()
        path = tmp_path / "permissions.json"
        path.write_text("{not json", encoding="utf-8")

        reopened = mod.PluginPermissionStore(path=str(path), declaredProvider=lambda pid: [])

        assert reopened.isGranted("reader", "read:events") is False
        assert reopened.grantedFor("reader") == []
        assert reopened.snapshot()["corrupt"] is True, (
            "读数面不暴露「坏了」——面板会显示一张空授权表，看上去像「还没人确认过」")

    def testRevokeOfSomethingNotGrantedIsNamedNotSilent(self, store):
        with pytest.raises(Exception) as caught:
            store.revoke("reader", "read:events", grantedBy="admin-1")
        assert getattr(caught.value, "reason", "") == "not_granted", (
            "撤销一条不存在的授予却报成功——审计里会留下一条从未生效的撤销记录")


class TestAuditIsNotSkippable:
    def testGrantIsReadableBackFromTheExistingAuditSurface(self, store, audit):
        """审计写进既有 `AuditLogger` 的表，不新造平行体系（教义第 6 条）；
        判据按真产物读回，不是「函数被调了一次」——替身调用成功而库里没这条，等于没记。
        """
        from neurova.security.audit_logger import AuditEventType

        store.grant("reader", "read:events", grantedBy="admin-1")

        entries = [e for e in audit.query(event_type=AuditEventType.PERMISSION_CHANGE)
                   if e.resource_id == "reader"]
        assert len(entries) == 1, "授予没进审计：事后无从知道是谁确认的（读到 %s 条）" % len(entries)
        entry = entries[0]
        assert entry.user_id == "admin-1"
        assert entry.action == "plugin_permission_grant"
        assert "read:events" in json.dumps(entry.details, ensure_ascii=False)

    def testRevokeIsAuditedToo(self, store, audit):
        from neurova.security.audit_logger import AuditEventType

        store.grant("reader", "read:events", grantedBy="admin-1")
        store.revoke("reader", "read:events", grantedBy="admin-2")

        actions = [(e.action, e.user_id)
                   for e in audit.query(event_type=AuditEventType.PERMISSION_CHANGE)
                   if e.resource_id == "reader"]
        assert ("plugin_permission_revoke", "admin-2") in actions, (
            "只记授予不记撤销——审计里读不出「现在到底有没有」")

    def testGrantDoesNotTakeEffectIfAuditWriteFails(self, store, audit, monkeypatch):
        mod = _permissions()
        monkeypatch.setattr(mod, "log_audit", lambda *a, **kw: False)

        with pytest.raises(Exception) as caught:
            store.grant("reader", "read:events", grantedBy="admin-1")

        assert getattr(caught.value, "reason", "") == "audit_write_failed"
        assert not store.isGranted("reader", PluginPermission.READ_EVENTS)
        reopened = mod.PluginPermissionStore(path=store.path,
                                             declaredProvider=lambda pid: ["read:events"])
        assert not reopened.isGranted("reader", PluginPermission.READ_EVENTS), (
            "内存回滚了、盘上留着——重启后这条越权授予又活了")


class TestEventBusIsReallyGated:
    """framework_enforced 两档的中介点就是 `BasePlugin` 的三方法；这里用真实例、真替身总线。"""

    class _Probe(BasePlugin):
        async def on_initialize(self):
            pass

        async def on_start(self):
            pass

        async def on_stop(self):
            pass

        async def on_destroy(self):
            pass

    def _instance(self, monkeypatch, plugin_id="reader"):
        mod = _permissions()
        from neurova.plugins.plugin_manifest import parse_manifest

        monkeypatch.setattr(mod, "getPermissionStore",
                            lambda *a, **kw: self._grantedStore(plugin_id))
        return self._Probe(parse_manifest({"plugin_id": plugin_id, "name": plugin_id,
                                           "version": "1.0.0"}))

    def _grantedStore(self, plugin_id, granted=()):
        class _S:
            def isGranted(self, pid, perm):
                return pid == plugin_id and perm.value in granted

        return _S()

    def testSubscribeWithoutReadEventsIsRefused(self, monkeypatch):
        plugin = self._instance(monkeypatch)
        bus = _RecordingBus()
        plugin.event_bus = bus

        with pytest.raises(Exception) as caught:
            plugin.subscribe("message.received", lambda e: None)

        assert getattr(caught.value, "reason", "") == "permission_not_granted"
        assert bus.subscribed == [], "拒了却没拦住：总线已经收到订阅了"

    def testPublishWithoutEmitEventsIsRefused(self, monkeypatch):
        plugin = self._instance(monkeypatch, "shouter")
        bus = _RecordingBus()
        plugin.event_bus = bus

        with pytest.raises(Exception) as caught:
            plugin.publish_event("x", {"a": 1})

        assert getattr(caught.value, "reason", "") == "permission_not_granted"
        assert bus.published == []

    def testPermissionIsCheckedBeforeTheMissingBusWarning(self, monkeypatch):
        """没接总线时也要先过权限门——否则「忘了设总线」会掩盖越权调用。"""
        plugin = self._instance(monkeypatch)
        plugin.event_bus = None

        with pytest.raises(Exception) as caught:
            plugin.subscribe("message.received", lambda e: None)

        assert getattr(caught.value, "reason", "") == "permission_not_granted", (
            "未授予的订阅被降级成一条 warning：调用方拿到 None 继续跑（§6-126 那一族）")

    def testGrantedSubscribeReachesTheBus(self, monkeypatch):
        mod = _permissions()
        from neurova.plugins.plugin_manifest import parse_manifest

        monkeypatch.setattr(mod, "getPermissionStore",
                            lambda *a, **kw: self._grantedStore("reader", {"read:events"}))
        plugin = self._Probe(parse_manifest({"plugin_id": "reader", "name": "reader",
                                             "version": "1.0.0"}))
        bus = _RecordingBus()
        plugin.event_bus = bus

        plugin.subscribe("message.received", lambda e: None)

        assert bus.subscribed == ["message.received"]


class _RecordingBus:
    def __init__(self):
        self.subscribed = []
        self.unsubscribed = []
        self.published = []

    def subscribe(self, name, handler):
        self.subscribed.append(name)

    def unsubscribe(self, name, handler):
        self.unsubscribed.append(name)

    def publish(self, name, data=None):
        self.published.append((name, data))
