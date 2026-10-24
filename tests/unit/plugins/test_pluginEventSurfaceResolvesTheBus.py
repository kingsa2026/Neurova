# -*- coding: utf-8 -*-
r"""插件事件面必须真落到总线上——过了权限门之后不许静默 no-op（§6-412 批 P-4）。

用户裁：接（现取单例），且须与权限归类同批。

## 现查实况：门已经有了，缺的是门后那条路

`BasePlugin.subscribe/unsubscribe/publish_event`（`neurova/plugins/base_plugin.py:220-246`）
每条都**先**过 `_requirePermission(...)`（`read:events`／`emit:events`，未逐项确认即抛
`PluginError("permission_not_granted")`），然后才是：

```python
if self._event_bus:
    self._event_bus.subscribe(event_name, handler)
else:
    self._logger.warning("事件总线未设置，无法订阅事件: %s", event_name)
```

而 `self._event_bus` 在**生产侧从来没有人赋值**：`plugin_manager.py` 里连 `event_bus`
这个词都不出现，全仓 `plugin.event_bus = …` 的命中点只有 `tests/unit/test_base_plugin.py`
的 255／283／304 三处（测试自己设的）。⇒ 一个**已按 §6-155 逐项确认过权限**的插件调
`publish_event()`，效果是打一条 warning 然后什么都没发生——比"没接线"更坏的是它看起来
走了正常分支。`unsubscribe` 那一支连 warning 都没有，静默到底。

这与 `core/base_module.py:115` 那段注释记的是**同一条根因**（注入位从不被填 ⇒ 恒走 None 分支），
那边早已用"调用时现取 `get_event_bus()`"收口（并解释了为什么不能冻结在构造期：
重置全局单例之后，已建对象会对着一条已退役的总线发事件）。插件这一族当时没被扫到——
本票就是那一条的第 5 条扫荡补齐。

## 裁定的风险面在实装里比票面上小（据实更正）

我在票里写过"接＝给第三方装载物打开全仓事件写口"。读实装后更正：**权限门已存在且逐项确认**
（`plugin_permissions.permissionIsGranted(plugin_id, surface)`，未授予直接抛，
且 `test_permissionGateIsCheckedBeforeTheBusPresenceCheck` 钉死了"门在探测之前"的顺序）。
本批只把门后那条 no-op 分支换成真总线，**不动**门的语义、不新增能力面词汇
（能力面单点仍在 `skills/permissions.py:KNOWN_CAPABILITY_KEYS`，见 `PluginFrameworkSurface`
的 docstring）。所以"与权限归类同批"这一条的落点是：**验证门仍然先于路**，而不是新造一套门。

## 判据的对照

- **行为正检**：不给插件注入任何 bus（生产形态），授予 `emit:events` 后 `publish_event`
  必须**在真全局总线上看得见**（`get_event_bus()` 的计数与 handler 收包）。
- **读写都通**：授予 `read:events` 后 `subscribe` 收得到别的发布者投来的事件；
  `unsubscribe` 之后不再收到（那一支今天连 warning 都没有，是三条通道里最静默的）。
- **门不许被绕过**：未授予时即便总线现取可得，也必须先抛 `permission_not_granted`
  且**一次都不落到总线上**。
- **单源口径**：解析总线这件事不许有两个形状——两个族在无注入时解析到**同一个** bus 对象，
  且 `if self._event_bus:` 这一形在 `neurova/` 里不得再作为分支存在（反向守卫）。
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
NEUROVA_ROOT = REPO_ROOT / "neurova"

from neurova.plugins import plugin_permissions
from neurova.plugins.base_plugin import BasePlugin
from neurova.plugins.plugin_manifest import PluginManifest, SemVersion


class _Probe(BasePlugin):
    async def on_initialize(self) -> None:
        pass

    async def on_start(self) -> None:
        pass

    async def on_stop(self) -> None:
        pass

    async def on_destroy(self) -> None:
        pass


def _plugin(plugin_id: str) -> _Probe:
    return _Probe(PluginManifest(plugin_id=plugin_id, name="Probe", version=SemVersion("1.0.0")))


def _grant(tmp_path, monkeypatch, granted):
    """铺授权文件而不是调 `grant()`：走它每铺一次就往真实审计库写一条记录。"""
    import json

    from neurova.plugins.plugin_permissions import STORE_VERSION

    path = tmp_path / "permissions.json"
    path.write_text(
        json.dumps({"version": STORE_VERSION,
                    "grants": {"probe-plugin": {v: {"granted_by": "qa", "kind": "surface"}
                                                for v in granted}}},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(plugin_permissions, "getPermissionStore",
                        lambda *a, **kw: plugin_permissions.PluginPermissionStore(path))


@pytest.fixture
def cleanBus():
    from neurova.core.event_bus import get_event_bus, reset_event_bus

    reset_event_bus()
    bus = get_event_bus()
    yield bus
    reset_event_bus()


class TestGrantedPluginReachesTheRealBus:

    def test_publishWithoutAnyInjectedBusLandsOnTheGlobalBus(self, tmp_path, monkeypatch, cleanBus):
        _grant(tmp_path, monkeypatch, ["emit:events"])
        plugin = _plugin("probe-plugin")
        assert plugin._event_bus is None, "前置不成立：本格测的就是『没人注入』那一形"

        name = "pluginProbe.emit.%s" % uuid.uuid4().hex[:8]
        before = cleanBus.publishedCount()
        plugin.publish_event(name, {"phase": 1})

        assert cleanBus.publishedCount() == before + 1, (
            "已授予 emit:events 的插件发布事件后，总线上一个计数都没多——"
            "`if self._event_bus:` 恒假，调用只留下一条 warning"
        )

    def test_subscribeWithoutAnyInjectedBusReceivesEvents(self, tmp_path, monkeypatch, cleanBus):
        _grant(tmp_path, monkeypatch, ["read:events", "emit:events"])
        plugin = _plugin("probe-plugin")
        name = "pluginProbe.recv.%s" % uuid.uuid4().hex[:8]
        got = []

        plugin.subscribe(name, lambda event: got.append(event))
        cleanBus.publish(name, {"hello": 1})

        assert got, "订阅没落到真总线上：插件声明的 read:events 框架面是空头支票"
        assert got[0].data == {"hello": 1}, got[0].data

    def testUnsubscribeActuallyStopsDelivery(self, tmp_path, monkeypatch, cleanBus):
        _grant(tmp_path, monkeypatch, ["read:events"])
        plugin = _plugin("probe-plugin")
        name = "pluginProbe.unsub.%s" % uuid.uuid4().hex[:8]
        got = []

        def handler(event):
            got.append(event)

        plugin.subscribe(name, handler)
        cleanBus.publish(name, 1)
        plugin.unsubscribe(name, handler)
        cleanBus.publish(name, 2)

        assert [e.data for e in got] == [1], (
            "退订没生效（这一支改前连 warning 都没有，静默到底）：%s" % [e.data for e in got]
        )


class TestPermissionGateStillComesFirst:
    """裁定的另一半：门先于路——本批不得把"没注入"这件事变成新的绕门通道。"""

    def test_ungrantedPluginRaisesAndNothingReachesTheBus(self, tmp_path, monkeypatch, cleanBus):
        from neurova.plugins.plugin_errors import PluginError

        _grant(tmp_path, monkeypatch, [])
        plugin = _plugin("probe-plugin")
        name = "pluginProbe.denied.%s" % uuid.uuid4().hex[:8]
        before = cleanBus.publishedCount()

        with pytest.raises(PluginError) as caught:
            plugin.publish_event(name, {"x": 1})
        assert caught.value.reason == "permission_not_granted"
        with pytest.raises(PluginError) as caught:
            plugin.subscribe(name, lambda e: None)
        assert caught.value.reason == "permission_not_granted"

        assert cleanBus.publishedCount() == before, "未授予的调用落到了总线上——门被绕过去了"

    def test_explicitInjectionStillWinsOverTheFallback(self, tmp_path, monkeypatch):
        """`event_bus` 属性仍是**显式覆盖**通道（测试与特殊装配用），不许被现取逻辑吃掉。"""
        from unittest.mock import MagicMock

        _grant(tmp_path, monkeypatch, ["emit:events"])
        plugin = _plugin("probe-plugin")
        injected = MagicMock()
        plugin.event_bus = injected
        plugin.publish_event("pluginProbe.override", {"v": 1})

        assert injected.publish.call_count == 1, "注入的总线被绕过了——覆盖通道就是第二条口径"


class TestBusResolutionHasOneShape:
    """两个族解析到同一条总线，且 `if self._event_bus:` 那一形不再作为分支存在。"""

    def testBothFamiliesResolveToTheSameBusObject(self):
        from neurova.core.base_module import BaseModule

        class _Mod(BaseModule):
            def on_initialize(self) -> None:
                pass

            def on_start(self) -> None:
                pass

            def on_stop(self) -> None:
                pass

        plugin = _plugin("probe-plugin")
        module = _Mod()
        assert plugin._resolveEventBus() is module._resolveEventBus(), (
            "插件族与模块族解析到的不是同一条总线——两条口径迟早又分家"
        )

    def test_pluginFamilyKeepsNoPresenceBranchOnTheInjectionSlot(self):
        """`plugins/base_plugin.py` 里不得再留 `if self._event_bus:` 这一形。

        范围为什么只到这一族（不是全仓禁这个语法）：同形状在 `shared_core/infrastructure.py`
        是**合法**的——本批现查该类在 `:130` 真的会 `self._event_bus = EventBus()`
        （按 `enable_event_bus` 配置），它的 `if` 是"可选组件在不在"的存在性判断，
        不是"注入位从没被人填过"的那条根因。把它一起扫掉等于改坏正确的代码。
        """
        import ast as _ast

        path = NEUROVA_ROOT / "plugins" / "base_plugin.py"
        tree = _ast.parse(path.read_text(encoding="utf-8"))
        offenders = []
        for node in _ast.walk(tree):
            if isinstance(node, _ast.If):
                text = _ast.unparse(node.test).strip()
                if text in ("self._event_bus", "not self._event_bus"):
                    offenders.append((node.lineno, text))
        assert not offenders, (
            "插件族的三条通道又回到『拿注入位当存在性判断』：%s——解析只有 "
            "`_resolveEventBus()` 一个形状（注入优先、未注入现取单例）" % offenders
        )

    def test_scanRootIsReachableAndNonTrivial(self):
        """面自证：这条 structural 判据真的看得见那三条通道所在的档，根指错时不得作数。"""
        from tests import ast_scan

        enumerated = len(ast_scan.sourceRefsUnder(NEUROVA_ROOT, ".py"))
        assert enumerated >= 800, (
            "生产树现读 %d 个 .py——NEUROVA_ROOT 指错时上一条的『零命中』是假绿" % enumerated)
        candidates = ast_scan.sourceRefsUnder(NEUROVA_ROOT, ".py", hints=("_event_bus",))
        assert len(candidates) >= 2, (
            "提到 `_event_bus` 的生产档只剩 %d 个——预筛或口径写窄了，上一条不作数" % len(candidates))
