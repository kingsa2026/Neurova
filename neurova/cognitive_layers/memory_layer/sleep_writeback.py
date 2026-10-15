"""睡眠整理结果写回（共享实现）

被两处复用：
- core/idle_tracker.py 空闲触发的整理
- agent_shutdown.py 关机时的整理

此前的问题：
- 关机路径只打日志，合并记忆直接丢弃
- 两处写回都只"新增合并记忆"，从未删除被合并的源记忆 → 记忆翻倍
- （§6-223 现量）退役与温度两条腿被归属校验整段拒——固化跑在没有请求边界的进程作用域里，
  而源行属别的 (neuser_id, user_id)；统计却照报 `added=2 / forgotten=0 / updated=N`，
  因为 `update_memory` 被拒时只回 False 不抛，计数把失败算成了成功
"""

from typing import Any, Dict

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def write_back_consolidation_result(memory_manager, result: Dict[str, Any]) -> Dict[str, int]:
    """把 run_sleep_cycle 的结果写回 MemoryManager。

    步骤:
    1. 合并产物（merged_from ≥2）新增一行并带上来源，随后在同一作用域内 soft-forget 它的源
    2. 归档记忆更新生命周期；未合并的活跃记忆按闲置衰减温度

    每一条动作都先进入**这一行自己的隔离作用域**（`request_scope`）再落——P1-6 的归属校验
    据此正常通过。不许改用 `agent_wide=True`：那是把越权写成契约（反向钉见
    `tests/unit/memory/test_sleepConsolidationBucketsByIsolationScope.py`）。

    Returns:
        {"added": int, "forgotten": int, "updated": int}——三个计数都只在被真的做成时才加。

    任何单条失败都不抛异常（写回失败不得阻断关闭流程）。
    """
    stats = {"added": 0, "forgotten": 0, "updated": 0}
    if not memory_manager or not result:
        return stats

    for memory in result.get("merged_memories", []) or []:
        neuser_id = getattr(memory, "neuser_id", None)
        user_id = getattr(memory, "user_id", None)
        try:
            with memory_manager.request_scope(neuser_id=neuser_id, user_id=user_id):
                # 新增与删除共用同一条契约：只有 ≥2 来源才是真实合并，才允许 remember() 新增
                # 并 soft-forget 它的源。单例簇（merged_from 为空或仅含自身）落归档/温度分支
                # ——否则每轮巩固把整库重新插入一遍（2026-09-05 事故：persist 库
                # 5040→10080→20160 指数翻倍）。
                if len(getattr(memory, "merged_from", None) or []) >= 2:
                    _write_back_product(memory_manager, memory, stats)
                elif getattr(memory, "is_archived", False):
                    try:
                        if memory_manager.update_memory(
                            memory_id=memory.id,
                            lifecycle_stage="archived",
                            temperature=getattr(memory, "temperature", 50.0),
                        ):
                            stats["updated"] += 1
                    except Exception as e:  # noqa: BLE001
                        logger.debug("归档更新失败 (%s): %s", memory.id, e)
                else:
                    _decay_single(memory_manager, memory, stats)
        except Exception as e:  # noqa: BLE001
            logger.warning("写回单条记忆异常: %s", e)

    logger.info(
        "睡眠整理写回完成: 新增 %s / 删除源 %s / 更新 %s",
        stats["added"], stats["forgotten"], stats["updated"],
    )
    return stats


def _write_back_product(memory_manager, memory, stats: Dict[str, int]) -> None:
    """插入合并产物（带来源），随后退役它吸收的那些源——全在产物自己的作用域内。"""
    categories = getattr(memory, "categories", None) or ["general"]
    category = categories[0] if isinstance(categories, list) else str(categories)
    try:
        # 显式 id：产物正文就是某条源的正文，不给 id 时 `remember()` 的内容门会把这次写入
        # 改道成"命中那条源"，紧接着它又进退役清单 ⇒ 活跃库里这条事实一条不剩
        # （§6-222 现量：默认分类下报 `added=1`，盘上只剩 2 条 forgotten 行）。
        # 顺带把来源落到产物行上——`MergeResult.source_ids` 此前只进 sleep_logs.json，
        # "这条记忆是那几条合出来的"在库内不可回查（§6-218 的断点）。
        memory_manager.remember(
            content=memory.content,
            category=category,
            importance=getattr(memory, "importance", 50.0),
            temperature=getattr(memory, "temperature", 50.0),
            id=memory.id,
            metadata={"merged_from": list(getattr(memory, "merged_from", None) or [])},
        )
        stats["added"] += 1
    except Exception as e:  # noqa: BLE001
        logger.warning("写回合并记忆失败 (%s): %s", memory.id, e)

    for sid in memory.merged_from:
        try:
            if memory_manager.forget(sid, soft=True):
                stats["forgotten"] += 1
        except Exception as e:  # noqa: BLE001
            logger.debug("删除源记忆失败 (%s): %s", sid, e)


def _decay_single(memory_manager, memory, stats: Dict[str, int]) -> None:
    """未合并的单例：把固化本轮算好的温度落回库——读数来源只认 `TemperatureEngine` 那一份。

    这里原来另写了一套"按闲置天数线性降 2 度/天"的公式，那是同功能的第二份实现（教义第 7 条），
    而且它读的 `last_accessed_at` 在 `MemoryRecord` 上根本没有（dataclass 没声明、`from_dict`
    也不映射）⇒ `days_idle` 恒 0，那套公式恒等于"原样写回"，从没减过任何东西
    （§6-223 现量：盘上 65.0 → 65.0）。衰减的权威实现是 `temperature.py` 的
    `on_decay`，`consolidate` 已经通过 `apply_sleep_decay` 把它算进 `memory.temperature`。
    """
    try:
        if memory_manager.update_memory(
            memory_id=memory.id,
            temperature=float(getattr(memory, "temperature", 50.0) or 50.0),
        ):
            stats["updated"] += 1
    except Exception as e:  # noqa: BLE001
        logger.debug("温度更新失败 (%s): %s", memory.id, e)
