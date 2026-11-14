"""睡眠整理的第二套实现退役锁（教义第 7 条，2026-11-14）。

现量归属（本批现算，不抄旧账）：`modules/sleep_module.py` 310 行、1 类 9 法；
它对记忆的"巩固/清理"全靠 `set_callbacks` 注入的回调，而 `set_callbacks`
全仓零调用 ⇒ 四个 `run_*_sleep_cycle` 即便被调用也只是计数器，不落任何盘；
manager 的这四个方法生产调用方为 0（/api/v1/sleep 全部读 SleepConsolidation）。
同一条链在选定那份（`sleep.py` 的 `SleepConsolidation`）上有聚类合并、
`merged_from≥2` 防翻倍写回、按作用域分桶与 duplication 守卫——第二份的
"不可替代部分"为零，且接通它等于绕过这些守卫双写记忆。

判据（教义第 7 条）：该功能在仓内只剩一处实现被消费。本档三格：
- 主格红在今天：模块/方法还活着（名字仍可 import / getattr）；
- 交付锁：真引擎的编排能力必须还在（与 test_SleepConsolidationHasOneImplementation
  分工——那边钉"选定的那份齐全"，这边钉"第二份不复活"）。
"""
from __future__ import annotations

import importlib

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

_RETIRED_METHODS = (
    "run_light_sleep_cycle",
    "run_rem_sleep_cycle",
    "run_deep_sleep_cycle",
    "run_dormant_cycle",
    "_ensure_sleep_module",
    "_collect_memories_for_sleep",
)


def testTheSecondImplementationIsGone():
    """主格：modules/sleep_module.py 不许再存在。"""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("neurova.cognitive_layers.memory_layer.modules.sleep_module")


def testManagerSleepCycleFacadeIsGone():
    """主格：门面上的四个周期方法与装配器不许再出现。"""
    for name in _RETIRED_METHODS:
        assert not hasattr(MemoryManager, name), (
            "%s 还挂在 MemoryManager 上 ⇒ 退役没闭环" % name
        )


def testTheChosenImplementationStillCarriesTheOrchestration():
    """交付锁（现值绿）：删第二份不许把真引擎的编排能力顺手删没。"""
    for name in ("consolidate", "run_sleep_cycle", "cluster_by_similarity",
                 "merge_cluster", "start_sleep", "wake"):
        assert callable(getattr(SleepConsolidation, name, None)), (
            "选定的那份缺 %s() ⇒ SleepModule 不是重复实现，而是唯一通路，退役判据不成立" % name
        )
