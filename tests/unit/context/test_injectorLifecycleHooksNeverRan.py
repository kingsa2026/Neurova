# -*- coding: utf-8 -*-
"""A2 红灯（§6-12 缺陷② + §6-5 家族的新命中点）：注入器的生命周期从未执行。

取证（2026-10-08，实测命令与输出见提交说明）：
- `UnifiedContextInjector.on_initialize/on_start/on_stop`(:224/:238/:242) 声明成
  `async def`，但体内**一个 await 都没有**（只有 log_info / subscribe_event /
  `_flush_cache()`，而 `_flush_cache` 在 :1163 是同步 def）。
- `BaseModule.initialize()`(:143) 是同步调用 `self.on_initialize()` → 协程被创建后
  丢弃（实测 `-W error::RuntimeWarning` 下打出
  `RuntimeWarning: coroutine 'UnifiedContextInjector.on_initialize' was never awaited`），
  `initialize()` 照样不抛，模块状态照走。
- 后果：`:228-230` 那三条 `context.build` / `context.invalidate_cache` /
  `context.set_priority` 订阅**一条都没挂上**（实测 `get_subscribers('context.build')`
  返回 0）。这是 §6-5 "漏 await" 同族的类级形态，全仓 AST 扫同类命中点**只有这 3 处**。
- 另一格：`injector.py:36-69` 为 `BaseModule` 准备了 ImportError 降级替身，自带第三份
  事件面（私有 `_event_handlers` + `emit_event` 里 `except Exception: pass` 吞 handler
  异常）。而 `neurova.core.base_module` 是仓内模块，恒可导入（实测
  `_BASE_MODULE_AVAILABLE=True`），所以那份替身是"自己造依赖缺失"的逃生门。
- 真 `BaseModule` **根本没有 `subscribe_event`**（实测 hasattr=False）——即使有人
  await 了 on_initialize，那三行也会 AttributeError。缺的是把订阅能力收到基类这
  一份公开面上，不是在子类里各配一套私有 handlers。

判据四条各钉一格：① initialize() 之后订阅真的在总线上；② 生命周期钩子不得"async
但体内无 await"（判 AST 形态，覆盖全仓，防同类回流）；③ 订阅入口只有基类那一份；
④ injector 里不得再有第二份 BaseModule 定义。
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from tests import ast_scan
from neurova.context.injector import UnifiedContextInjector
from neurova.core.base_module import BaseModule
from neurova.core.event_bus import EventBus

INJECTOR_PATH = Path(__file__).resolve().parents[3] / "neurova" / "context" / "injector.py"
LIFECYCLE_HOOKS = ("on_initialize", "on_start", "on_stop")


@pytest.fixture
def probeBus():
    return EventBus()


def _makeInjector(bus):
    return UnifiedContextInjector(memory_manager=object(), event_bus=bus)


def testInitializeRegistersSubscriptionsOnTheBus(probeBus):
    """① 生命周期跑完，三条 context.* 订阅必须挂在被注入的那条总线上。

    现状红：协程被丢弃 → 订阅数为 0。
    """
    injector = _makeInjector(probeBus)
    injector.initialize()

    for eventName in ("context.build", "context.invalidate_cache", "context.set_priority"):
        assert probeBus.get_subscribers(eventName), (
            f"{eventName} 无订阅者——on_initialize 的订阅从未执行"
            "（async 钩子被同步 initialize() 丢成协程对象）"
        )


def testStopFlushesCacheViaLifecycle(probeBus):
    """生命周期后半段同样得真执行：initialize → start → stop 全链不得静默空转。"""
    injector = _makeInjector(probeBus)
    injector.initialize()
    injector.start()
    assert injector.get_state().value == "running"

    injector.stop()
    assert injector.get_state().value == "stopped"
    assert probeBus.get_subscribers("context.build"), "stop 后订阅应仍在（退役由 unsubscribe 管）"


def testNoAsyncHookWithoutAwaitInBody():
    """② 反向守卫（全仓）：生命周期钩子不得声明成 async 却体内零 await。

    这条钉的是代码形态而不是文件名——`BaseModule.initialize/start/stop` 是同步 API，
    子类把钩子写成 async 就等于把执行权丢掉；真需要 async 时必须体内有 await，
    由调用方改造另开一批。
    """
    offenders = []
    root = INJECTOR_PATH.parents[1]
    # 枚举与解析走 tests/ast_scan.py 的共享预算（Issue #148：受保护子集里不得
    # 再出现自带 rglob + ast.parse 的第二份实现）。
    for py, tree in ast_scan.parsedModules(root):
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            bases = {ast.unparse(b).rsplit(".", 1)[-1] for b in cls.bases}
            if not (bases & {"BaseModule", "MemoryModule"}):
                continue
            for fn in cls.body:
                if isinstance(fn, ast.AsyncFunctionDef) and fn.name in LIFECYCLE_HOOKS:
                    hasAwait = any(
                        isinstance(n, ast.Await) for sub in fn.body for n in ast.walk(sub)
                    )
                    if not hasAwait:
                        rel = py.relative_to(root.parent).as_posix()
                        offenders.append(f"{rel}:{fn.lineno} {cls.name}.{fn.name}")
    assert not offenders, (
        "async 声明 + 零 await 实体的生命周期钩子会被同步 initialize() 丢成协程对象，"
        f"钩子一次都不执行：{offenders}"
    )


def testSubscribeEventIsOnBaseModuleNotPerClassPrivateHandlers():
    """③ 订阅入口只有基类那一份公开面，且走的是被注入的总线。"""
    assert hasattr(BaseModule, "subscribe_event"), (
        "BaseModule 没有 subscribe_event——子类只能各配一套私有 handlers（第三份总线）"
    )
    probeBus = EventBus()
    injector = _makeInjector(probeBus)
    sentinel = lambda event: None  # noqa: E731 - 探针
    injector.subscribe_event("probe.event", sentinel)
    assert any(s.handler is sentinel for s in probeBus.get_subscribers("probe.event"))


def testInjectorDoesNotRedefineBaseModule():
    """④ 降级替身退役：injector.py 里不得再定义第二份 BaseModule。

    `neurova.core.base_module` 是仓内模块、恒可导入，用 try/except ImportError 给自己
    造一个"依赖缺失"再兜底，等于同时留着两份契约（且兜底那份把 handler 异常吞成 pass）。
    """
    tree = ast.parse(INJECTOR_PATH.read_text(encoding="utf-8"))
    redefined = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "BaseModule"
    ]
    assert not redefined, (
        f"neurova/context/injector.py:{redefined} 仍自带 BaseModule 替身——"
        "同一功能两份实现，判据只咬得到其中一份"
    )


def testCoroutinesAreNotSilentlyDiscardedByInitialize():
    """行为反证：initialize() 不得留下未等待的协程（漏 await 的直接可观测形态）。

    用 `inspect.iscoroutinefunction` 判钩子契约，比捕 RuntimeWarning 稳——后者在
    GC 时才发，归因不到语句。
    """
    injector = _makeInjector(EventBus())
    assert not inspect.iscoroutinefunction(injector.on_initialize), (
        "on_initialize 仍是协程函数，而 BaseModule.initialize() 同步调用它 → 钩子不执行"
    )
