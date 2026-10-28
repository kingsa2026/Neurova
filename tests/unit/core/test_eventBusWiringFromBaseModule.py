# -*- coding: utf-8 -*-
"""A1 红灯（§6-12 缺陷①）：`BaseModule` 的广播承诺从未生效。

取证（2026-10-08，A0 批）：
- `core/base_module.py:83/:115` 调 `self._event_bus.emit(...)`，而 `core/event_bus.py`
  的公开入口是 `publish`(:168)/`publish_async`(:219)——**没有 emit**。
- 全仓没有任何一处给 `event_bus` 传非 None（`base_module.py:39`、`idle_tracker.py:90`、
  `provider_manager.py:509` 全是形参转发），于是 `if self._event_bus:` 恒假。
  两处广播因此**一次都不执行**——`initialize/start/stop`(:141-174) 的每次状态变更、
  `idle_tracker.py:602` 的 `phase.changed` 都只写在日志里，总线上一片空白。

后果不是"少几条事件"，而是 `/v1/logs/events`（`api/endpoints/logs.py:72` 读
`get_event_bus().get_event_log()`）这个**现役读面**永远看不到模块生命周期——
写了没人读、读了恒为空，两头都是断点。

判据方向（三条各钉一格，缺一格就能静默回流）：
① 默认构造（不注入）也必须广播——取的是那份唯一的全局入口，不是再造一条总线；
② 显式注入时**只走注入那一份**，不得回落到全局（否则测试与生产互相看不见）；
③ `emit_event` 的载荷要带上 `MODULE_ID`（订阅者据此区分是哪个模块，缺它就退化成
   无归属事件，与 §6-45 "归因不到就不占槽" 同一纪律）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from neurova.core.base_module import BaseModule, ModuleState
from neurova.core.event_bus import Event, EventBus, get_event_bus, reset_event_bus
from tests.ast_scan import parseSource

BASE_MODULE_PATH = Path(__file__).resolve().parents[3] / "neurova" / "core" / "base_module.py"


class _ProbeModule(BaseModule):
    """最小具体子类：生命周期钩子空转，只观察广播面。"""

    def on_initialize(self) -> None:  # noqa: D102 - 探针
        return None

    def on_start(self) -> None:  # noqa: D102 - 探针
        return None

    def on_stop(self) -> None:  # noqa: D102 - 探针
        return None


def _collector(into: list):
    def handler(event: Event) -> None:
        into.append(event)

    return handler


@pytest.fixture
def freshGlobalBus():
    """把全局单例换成干净的一条，用完原样交还——不留在跨用例共享态里。"""
    reset_event_bus()
    bus = get_event_bus()
    yield bus
    reset_event_bus()


def testDefaultConstructionBroadcastsStateChange(freshGlobalBus):
    """① 默认构造就该广播。现状：`_event_bus` 恒 None → 总线零事件。"""
    received: list = []
    freshGlobalBus.subscribe("module.state_changed", _collector(received))

    module = _ProbeModule(module_id="probe_default")
    module.set_state(ModuleState.RUNNING)

    assert received, "默认构造的模块变更状态后总线上没有事件——广播承诺从未生效"
    event = received[0]
    assert event.data["module_id"] == "probe_default"
    assert event.data["new_state"] == ModuleState.RUNNING.value


def testInjectedBusIsUsedAndDoesNotFallBackToGlobal(freshGlobalBus):
    """② 注入哪条就走哪条，不得同时污染全局（两边都要能各自归因）。"""
    injected: list = []
    globalSeen: list = []
    probe = EventBus()
    probe.subscribe("module.state_changed", _collector(injected))
    freshGlobalBus.subscribe("module.state_changed", _collector(globalSeen))

    module = _ProbeModule(config={}, event_bus=probe, module_id="probe_injected")
    module.set_state(ModuleState.STOPPED)

    assert len(injected) == 1, "注入的总线上没收到事件——emit 落点接错或仍恒走 None 分支"
    assert globalSeen == [], "注入后仍向全局广播，等于同时存在两条事实源"


def testEmitEventCarriesModuleIdAndPayload(freshGlobalBus):
    """③ `emit_event` 走通并带归属（`idle_tracker.py:602` 是它的现役调用者）。"""
    received: list = []
    freshGlobalBus.subscribe("phase.changed", _collector(received))

    module = _ProbeModule(module_id="probe_phase")
    module.emit_event("phase.changed", {"idle": True})

    assert len(received) == 1, "emit_event 未落到总线"
    assert received[0].data["module_id"] == "probe_phase"
    assert received[0].data["idle"] is True


def testNoEmitAttributeOnEventBus():
    """反向守卫（防回流）：base_module 里不得再出现 `self._event_bus.emit(...)`。

    判 AST 里的调用形态，不钉词——本文件说明文字也提到 emit，钉词会把自己钉红。
    """
    tree = parseSource(BASE_MODULE_PATH.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "emit"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "_event_bus"
        ):
            offenders.append(node.lineno)
    assert not offenders, (
        f"neurova/core/base_module.py:{offenders} 仍调 `_event_bus.emit(...)`——"
        "core/event_bus.py 只有 publish(:168)，接线后走通即 AttributeError"
    )
