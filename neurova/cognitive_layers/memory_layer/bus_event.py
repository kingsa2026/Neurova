# -*- coding: utf-8 -*-
"""记忆域事件名常量表（§6-12 总线合一后的唯一词汇表）。

本文件**曾经**是第二份事件总线实现：`EventBus`(`on/off/emit/aemit`) + `MemoryModule`
抽象基类 + `ModuleHealth`。2026-10-08 A3a 按教义第 7 条把它与
`neurova/core/event_bus.py` 逐项比对后退役，理由记在这里，防止有人按旧文件名找总线：

- 选定 `core/event_bus.py` 为唯一实现。逐项证据：它有全局单例（`get_event_bus():324`，
  DCL + RLock）、有优先级/一次性订阅/模块归属、有事件日志且**日志有现役读面**
  （`api/endpoints/logs.py:72/106` 走 `get_event_log()`）、`publish` 返回 handler 结果；
  而这份只有一个进程内 dict，且 `manager.py:185` 是**每个 manager 自建一条私有实例**，
  对外出口 `manager.py:832` 的 `bus` 属性全仓零调用方——所以 MEMORY_* 事件不是
  "发了没人订"，是**发在一条别人拿不到的总线上**。
- `MemoryModule` 从未被继承，其 `init(bus, config)` 签名与各模块实际 `init()` 不符；
  `ModuleHealth` 零引用。二者随总线一并退役。
- 事件名常量留在记忆域（这是本域的词汇表，不跟总线实现走）。持有者改名
  `MemoryEventName`：与 `memory_stream.py:38` 的 `MemoryEvent`（那是流水账用的
  dataclass，另一套语义）不再同名——同包两个同名不同义的符号本身就是故障源，
  另格登记见台账 §6-51。
- 六个零发射零订阅的常量（`MEMORY_CONSOLIDATED`/`MEMORY_CONFLICT`/`TEMPERATURE_UPDATED`
  /`BUFFER_FLUSHED`/`SLEEP_STARTED`/`SLEEP_COMPLETED`，实测全仓除本文件外命中 0）
  随本次收口删除——与 P2-10 已删的 `TOOL_INVOKED`/`METACOGNITION_EVALUATED` 同族。
  睡眠周期那格若要恢复"睡眠完成即通知"的能力，属 §6-37/B5 那批产品裁决，不在本批。
"""

from __future__ import annotations


class MemoryEventName:
    """模块间通信的事件名（单一事实源）。

    发送方：`neurova/cognitive_layers/memory_layer/manager.py`（经共享总线
    `publish(name, payload, source="memory_manager")`）。订阅方在共享总线侧，
    任何模块 `from neurova.core.event_bus import get_event_bus` 后即可 `subscribe`。
    """

    MEMORY_CREATED = "memory_created"
    MEMORY_ACCESSED = "memory_accessed"
    MEMORY_UPDATED = "memory_updated"
    MEMORY_DELETED = "memory_deleted"

    #: 本域会发出的全部事件名——统计面按它数订阅者，新增事件名必须同步这一份，
    #: 否则读数会静默漏计（这是断点，不是兜底默认能盖住的）。
    ALL = (MEMORY_CREATED, MEMORY_ACCESSED, MEMORY_UPDATED, MEMORY_DELETED)
