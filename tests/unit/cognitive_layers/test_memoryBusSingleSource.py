# -*- coding: utf-8 -*-
"""A3a（§6-12 总线合一）：同一功能仓内只剩一份实现被消费，且 MEMORY_* 发在**共享**总线上。

取证（2026-10-08，逐条实测，未沿用台账旧描述）：
- 全仓有**两份** EventBus 实现：`core/event_bus.py:58`（`publish/subscribe`，DCL 单例
  `get_event_bus():324`，带优先级、一次性订阅、模块归属、事件日志与有界异步队列）与
  `cognitive_layers/memory_layer/bus_event.py:125`（`on/off/emit/aemit` + `emit_count`）。
- 消费者面实测：`bus_event` 只被 `memory_layer/manager.py:37` 一处导入，且
  `manager.py:185` 是 `self._bus = EventBus()`——**每个 manager 自建一条私有总线**，
  其对外出口 `manager.py:832` 全仓零调用方。于是 `manager.py:1281/1432/1801/1892/1934`
  五处 MEMORY_* 不是"发了没人订"，而是**发在一条别人根本拿不到的总线上**。
- `get_stats()`(:2115-2116) 读的 `bus_events` / `bus_handlers` 因此恒等于私有实例的读数，
  与全局那条总线无关——这正是台账 §6-12 原句"bus_handlers 恒为 0"的真实成因。
- `bus_event.py` 里的 `MemoryModule`/`ModuleHealth` 全仓零导入（`WorkingMemoryModule`
  是另一个符号，不算），且 `MemoryModule.init(bus, config)` 与各模块实际 init() 签名不符。

选定 `core/event_bus.py` 为唯一实现，依据四条逐项比（正确性/覆盖面/可测性/调用方数量）：
它有单例、有优先级与一次性订阅、有事件日志且**日志有现役读面**
（`api/endpoints/logs.py:72/106` 走 `get_event_log()`），调用方 3 处 vs `bus_event` 的 1 处。
`bus_event` 不可替代的部分只有 **MEMORY_* 事件名常量**（属记忆域的词汇表，留在原模块，
不跟总线实现一起走）。

本批判据五条：① 全仓 `class EventBus` 定义只许一处；② manager 发的 MEMORY_CREATED 必须
被共享总线上的订阅者收到，且事件名就是常量表那一个字符串；③ `get_stats()` 的两个读数
必须来自同一条共享总线（不再恒 0）；④ 私有总线实例不得再被 manager 持有；
⑤ §6-49——async 订阅者在无运行循环时不得被静默丢弃（必须留痕）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests import ast_scan

import pytest

from neurova.core.event_bus import get_event_bus, reset_event_bus

REPO_ROOT = Path(__file__).resolve().parents[3]
NEUROVA_ROOT = REPO_ROOT / "neurova"
MANAGER_PATH = NEUROVA_ROOT / "cognitive_layers" / "memory_layer" / "manager.py"
BUS_EVENT_PATH = NEUROVA_ROOT / "cognitive_layers" / "memory_layer" / "bus_event.py"

MEMORY_CREATED_NAME = "memory_created"


@pytest.fixture
def sharedBus():
    reset_event_bus()
    bus = get_event_bus()
    yield bus
    reset_event_bus()


@pytest.fixture
def manager(tmp_path):
    # 走生产构造（同 tests/integration/test_memory_emotion_min_score.py 的夹具形态），
    # 不手工塞私有字段
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    return MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="agent_a")


def _eventBusDefinitions() -> list:
    hits = []
    # 枚举与解析走 tests/ast_scan 的共享预算；预筛词是判据的**充分条件**
    # （谓词只认名为 EventBus 的 ClassDef，连这串字样都没有的文件不可能命中）。
    #
    # 面＝**整仓**，不是 `neurova/`：本谓词按 AST 认定义，`tests/` 或 `scripts/` 里再长出一个
    # 同名 ClassDef 就是第二份平行实装（各自订阅、各发各的事件，正是本判据要拦的那件事）。
    # 扩面实测零新命中，也不会自咬——本档没有名为 EventBus 的定义，只有字样出现在说明里。
    for ref in ast_scan.sourceRefsUnder(REPO_ROOT, ".py", ast_scan.textHints("class EventBus")):
        tree = ast.parse(ref.code)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "EventBus":
                hits.append(f"{ref.path.relative_to(REPO_ROOT).as_posix()}:{node.lineno}")
    return hits


def testOnlyOneEventBusImplementationRemains():
    """① 教义第 7 条的判据形态：该功能在仓内只剩一处实现被消费。"""
    surface = len(ast_scan.sourceRefsUnder(REPO_ROOT, ".py"))
    assert surface > 3000, (
        f"枚举面现读 {surface} 个 .py（根＝仓根）——根被缩回单族时，「只剩一份」只说明那一族里没别人")
    hits = _eventBusDefinitions()
    assert len(hits) == 1, (
        f"仓内有 {len(hits)} 份 `class EventBus`（{hits}）——两份平行实现各调各的，"
        "合并前任何一边加的订阅都不会被另一边看见"
    )


def testMemoryCreatedReachesSharedBus(sharedBus, manager):
    """② MEMORY_CREATED 必须落到共享总线，事件名取常量表那一个字符串。"""
    received = []
    sharedBus.subscribe(MEMORY_CREATED_NAME, lambda event: received.append(event))

    manager.remember("总线合一判据用的一条记忆", category="fact", importance=0.6)

    assert received, (
        "共享总线上收不到 MEMORY_CREATED——manager 仍把事件发进自己私有的总线实例"
    )
    assert received[0].name == MEMORY_CREATED_NAME
    assert received[0].data["content"] == "总线合一判据用的一条记忆"
    assert received[0].source == "memory_manager"


def testStatsReadBusCountsFromSharedBus(sharedBus, manager):
    """③ `get_stats()` 的两个读数必须来自同一条共享总线（原形态恒读私有实例）。"""
    received = []
    sharedBus.subscribe(MEMORY_CREATED_NAME, lambda event: received.append(event))
    manager.remember("stats 读数判据", category="fact", importance=0.5)

    stats = manager.get_stats()
    assert stats["bus_handlers"] >= 1, (
        f"bus_handlers={stats['bus_handlers']}——读的还是私有总线，"
        "全局订阅者对它不可见，这个统计格就是只写不读"
    )
    assert stats["bus_events"] >= 1, "bus_events 仍读私有实例的计数"


def testManagerDoesNotOwnABusInstance():
    """④ 反向守卫（判代码形态）：manager 不得再 `self._bus = EventBus()`。"""
    source = MANAGER_PATH.read_text(encoding="utf-8")
    ownInstance = re.search(r"self\._bus\s*=\s*EventBus\(\)", source)
    assert ownInstance is None, (
        "manager.py 仍自建总线实例——每个 manager 一条私有总线，"
        "外部永远拿不到（`manager.py:832` 那个出口即因此零调用方）"
    )


def testAsyncSubscriberLeavesATraceEitherWay(sharedBus):
    """⑤ §6-49：async 订阅者要么被执行、要么被记为丢弃——**不许两条都没发生**。

    `core/event_bus.py:189-201` 的形态是 `if sub.is_async: if self._async_queue: 入队;
    continue`——队列为 None 时既不执行也不计数也不打日志。A 轮之前无生产订阅者所以
    "恒空即恒对"，本批把 MEMORY_* 接上共享总线后这一格开始承重。
    判据写成不变量而不是分支断言：环境有 loop 就应被执行，没 loop 就必须留痕，
    两侧都不发生即静默丢数据。
    """
    calls = []

    async def handler(event):
        calls.append(event)

    sharedBus.subscribe("probe.async_event", handler)
    sharedBus.publish("probe.async_event", {"k": 1})

    assert calls or sharedBus.droppedAsyncCount() > 0, (
        "async 订阅者既没被执行也没被记为丢弃——事件静默消失（§6-49）"
    )
