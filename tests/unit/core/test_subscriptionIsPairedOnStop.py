# -*- coding: utf-8 -*-
"""订阅与退订必须成对：`stop()` 之后模块不得再被总线强引用（§6-419）。

## 现场读数（2026-10-25，本机实测）

受保护子集跑 83% 撞 SIGKILL（`Finished, code: 137`）的第四次。这次取到了逐档 RSS：
本机 16 GiB 无上限条件下整场峰值 **10.8 GiB**，而 CI 的 `runner.cpus: 4` 只给 8 GiB。
单向上涨不是某一档忽然吃满，而是**每档都在涨**：

```
tests/unit/api/test_channelWebhookAuthBeforeDispatch.py        1648MB -> 3245MB (+1597)
tests/unit/api/test_channelFeishuWebhookVoiceAndSenderUseAdapterFace.py  +805
tests/unit/api/test_channelWebhookResolvesAdapterByAgentTable.py         +952
tests/unit/api/test_channelManagementFaceTakesAgent.py                   +850
```

同族五档，每档各建一次 `create_app()`。

## 根因

`BaseModule.subscribe_event` 把 `level` 一路做成**只有订阅、没有退订**：
`EventBus.subscribe` 存住的是 `handler` 本身（bound method 持有 `self`），
`BaseModule` 侧又没有任何退订口 ⇒ 一个模块 `initialize()` 三次、被 `stop()` 三次，
总线上的强引用仍是三份。实测（`test_channelWebhookAuthBeforeDispatch` 同构最小复现）：

```
初始订阅面: {}
round#1: {'context.build': 2, 'context.invalidate_cache': 2, 'context.set_priority': 2}
round#2: {'context.build': 4, ...}          # 第三个 owner 又挂上来
round#3: {'context.build': 6, ...}
```

每轮死守 2 个 `UnifiedContextInjector`（`create_app` 各建一个），连带它们背后整张
记忆/上下文对象图；`tracemalloc` 显示 Python 堆只涨不到 1MB、`malloc_trim` 只归还 40MB，
**230MB/轮全在原生侧**——被强引用钉住的 `onnxruntime.InferenceSession` 原生内存。
同一个根因，`ba7c3a61` 那次只覆盖了 `reset_embedding_engine()` 那条丢弃引用的路。

## 判据（各自独立成格，缺一格就能静默回流）

① 订阅过的模块 `stop()` 后，该模块在每条总线上的订阅数归零；
② `stop()` 后模块实例**可被回收**（`weakref` 探针，钉的是"总线不再是活引用源"）；
③ `initialize` 与 `stop` 成对时不会误退别人的订阅（同一事件上另有订阅者仍在）；
④ 形状格：`BaseModule` 必须有退订口，且 `stop()` 真的调它（按 AST 认，不按词）。
"""

from __future__ import annotations

import ast
import gc
import weakref
from pathlib import Path

from neurova.core.base_module import BaseModule, ModuleState
from neurova.core.event_bus import EventBus
from tests.ast_scan import parseSource

BASE_MODULE_PATH = Path(__file__).resolve().parents[3] / "neurova" / "core" / "base_module.py"


class _SubscribingModule(BaseModule):
    """最小具体子类：`on_initialize` 订两个事件，`on_stop` 什么都不做（判据要求基类兜住）。"""

    def on_initialize(self) -> None:
        self.subscribe_event("probe.build", self._handleBuild)
        self.subscribe_event("probe.invalidate", self._handleInvalidate)

    def on_start(self) -> None:
        return None

    def on_stop(self) -> None:
        return None

    async def _handleBuild(self, data) -> None:
        return None

    async def _handleInvalidate(self, data) -> None:
        return None


def _subscriberCount(bus: EventBus, eventName: str) -> int:
    return len(bus._subscribers.get(eventName, []))


def _runLifecycle(module: BaseModule) -> None:
    module.initialize()
    module.start()
    module.stop()


def testStopReleasesEverySubscription():
    """① 一轮完整生命周期之后，该模块不得在总线上留订阅。"""
    bus = EventBus()
    module = _SubscribingModule(config={}, event_bus=bus, module_id="probe_paired")

    module.initialize()
    assert _subscriberCount(bus, "probe.build") == 1, "订阅没挂上，后续读数不算证据"

    module.start()
    module.stop()

    assert _subscriberCount(bus, "probe.build") == 0, (
        "stop() 之后 probe.build 上仍留着订阅——bound method 强引用着模块，"
        "每建一次模块就永久多一份对象图（受保护子集每档各建一次 app 的 137 就出在这里）"
    )
    assert _subscriberCount(bus, "probe.invalidate") == 0


def testStoppedModuleBecomesCollectable():
    """② 钉"总线不再是活引用源"：停掉之后模块必须能被回收。"""
    bus = EventBus()
    module = _SubscribingModule(config={}, event_bus=bus, module_id="probe_collectable")
    probe = weakref.ref(module)

    _runLifecycle(module)
    del module
    gc.collect()

    assert probe() is None, (
        "stop() 之后模块仍被回收不掉——持有者只可能是总线上的 bound method 订阅"
    )


def testStopOnlyRemovesItsOwnSubscriptions():
    """③ 反向控制：别人的订阅不许被顺手退掉（退订按模块归因，不是"整条清空"）。"""
    bus = EventBus()
    kept = []

    async def _foreignHandler(data) -> None:
        kept.append(data)

    bus.subscribe("probe.build", _foreignHandler, module_name="somebody_else")

    module = _SubscribingModule(config={}, event_bus=bus, module_id="probe_self")
    _runLifecycle(module)

    remaining = bus._subscribers.get("probe.build", [])
    assert len(remaining) == 1, f"stop() 把别人的订阅也退了：剩 {len(remaining)} 条"
    assert remaining[0].handler is _foreignHandler


def testBaseModuleHasAnUnsubscribeFaceAndStopCallsIt():
    """④ 形状格：退订口在基类里只有一处，且 `stop()` 真调它。

    按 AST 认 `stop` 函数体内的 `self.<退订方法>(...)` 调用，不按词——
    本文件说明文字里也有"退订"二字，钉词会把自己钉红。
    """
    tree = parseSource(BASE_MODULE_PATH.read_text(encoding="utf-8"))
    moduleClass = next(
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "BaseModule"
    )
    stopFn = next(
        n for n in moduleClass.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "stop"
    )
    calledAttrs = {
        node.func.attr
        for node in ast.walk(stopFn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
    }
    assert "unsubscribeAllEvents" in calledAttrs, (
        f"BaseModule.stop() 没有调退订口（实际调到：{sorted(calledAttrs)}）——"
        "订阅与退订不成对，模块停掉后仍被总线钉住"
    )
    assert any(
        isinstance(n, ast.FunctionDef) and n.name == "unsubscribeAllEvents"
        for n in moduleClass.body
    ), "BaseModule 缺少退订口 unsubscribeAllEvents"


# ── ② 生产装配点的成对性（教义第 5 条：同一根因的所有命中点）────────────────────
#
# 上面四格钉的是基类的成对口径；真正把内存顶上去的是**生产装配点**——
# `ContextOrchestrator.init_context_system()` 建出注入器并 `initialize()`，
# 而 agent 关停链此前只关它的 `context_pool`，注入器句柄根本没留住，
# 于是 `BaseModule.stop()` 那条退订路径在生产上**一次都走不到**（第一版修完读数
# 不变就是这个原因：基类是对的，装配点没接）。


def testContextSystemHasAShutdownPairAndAgentStopCallsIt():
    """装配点成对：`init_context_system` 建出的注入器必须有拆解口，且关停链调到它。"""
    from neurova.context.orchestrator import ContextOrchestrator
    import neurova.agent_shutdown as agentShutdown

    assert hasattr(ContextOrchestrator, "shutdownContextSystem"), (
        "ContextOrchestrator 没有拆解入口——init_context_system 建出的注入器"
        "在全局总线上挂着三条 bound method 订阅，没人退订"
    )

    source = Path(agentShutdown.__file__).read_text(encoding="utf-8")
    tree = parseSource(source)
    shutdownFn = next(
        n for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "shutdown_agent"
    )
    touched = {
        node.value
        for node in ast.walk(shutdownFn)
        if isinstance(node, ast.Constant) and node.value == "_unifiedInjector"
    }
    assert touched, (
        "agent 关停链没有取 `context_orchestrator._unifiedInjector`——"
        "注入器句柄不留在编排器上，退订口就没有调用者（生产上一条都走不到）"
    )


def testInitializedOnlyInjectorIsReleasedByItsUnsubscribeFace():
    """只 `initialize()`、没 `start()` 的模块：`stop()` 退不掉，退订口必须退得掉。

    这一格是上一格的**行为底座**，钉的是实测踩到的坑：`BaseModule.stop()` 只在
    RUNNING 态动作，而注入器在生产里只 initialize() 过 ⇒ 拿 stop() 当退订口会静默
    什么都不做（打一行 "not running" 就返回）。判据要求退订口本身幂等且无状态前置。
    """
    from neurova.context.injector import TokenBudget, UnifiedContextInjector

    bus = EventBus()

    async def _noop(data) -> None:
        return None

    injector = UnifiedContextInjector(memory_manager=None, token_budget=TokenBudget(max_total=100))
    injector._event_bus = bus
    injector.initialize()  # 只 initialize，不 start —— 与生产装配点一致
    assert injector.get_state() is ModuleState.INITIALIZED
    assert _subscriberCount(bus, "context.build") == 1, "注入器没把订阅挂上，本格不成立"

    injector.stop()  # 反证：非 RUNNING 态下 stop 不做退订
    assert _subscriberCount(bus, "context.build") == 1, (
        "stop() 在 INITIALIZED 态下真的做了事——那本批的退订口选型前提已变，回来重判"
    )

    released = injector.unsubscribeAllEvents()
    assert released == 3, f"退订口应退掉 3 条（context.build/invalidate_cache/set_priority），实得 {released}"
    assert _subscriberCount(bus, "context.build") == 0
    assert injector.unsubscribeAllEvents() == 0, "退订口必须幂等"
