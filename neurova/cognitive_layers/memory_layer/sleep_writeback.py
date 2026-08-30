"""睡眠整理结果写回（共享实现）

被两处复用：
- core/idle_tracker.py 空闲触发的整理
- agent_shutdown.py 关机时的整理

此前的问题：
- 关机路径只打日志，合并记忆直接丢弃
- 两处写回都只"新增合并记忆"，从未删除被合并的源记忆 → 记忆翻倍
"""

from typing import Any, Dict

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def write_back_consolidation_result(memory_manager, result: Dict[str, Any]) -> Dict[str, int]:
    """把 run_sleep_cycle 的结果写回 MemoryManager。

    步骤:
    1. 新增合并后的新记忆（merged_from 非空）
    2. 删除被合并的源记忆（soft forget，可恢复）
    3. 归档记忆更新生命周期；未合并的活跃记忆更新温度

    Returns:
        {"added": int, "forgotten": int, "updated": int}

    任何单条失败都不抛异常（写回失败不得阻断关闭流程）。
    """
    stats = {"added": 0, "forgotten": 0, "updated": 0}
    if not memory_manager or not result:
        return stats

    merged_memories = result.get("merged_memories", []) or []
    merge_results = result.get("merge_results", []) or []

    # 收集被合并的源记忆 id
    # 根因修复: 单例簇（未被合并的记忆）的 source_ids 只含它自己，此前也一并
    # soft-forget → 每次睡眠整理都会遗忘所有未合并记忆。只有 ≥2 个来源的
    # 簇才是真实合并，才允许删除源记忆。
    source_ids: set = set()
    for merge_result in merge_results:
        result_sources = getattr(merge_result, "source_ids", []) or []
        if len(result_sources) >= 2:
            source_ids.update(result_sources)

    for memory in merged_memories:
        try:
            if getattr(memory, "merged_from", None):
                categories = getattr(memory, "categories", None) or ["general"]
                category = categories[0] if isinstance(categories, list) else str(categories)
                try:
                    memory_manager.remember(
                        content=memory.content,
                        category=category,
                        importance=getattr(memory, "importance", 50.0),
                        temperature=getattr(memory, "temperature", 50.0),
                    )
                    stats["added"] += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning("写回合并记忆失败 (%s): %s", memory.id, e)
            elif getattr(memory, "is_archived", False):
                try:
                    memory_manager.update_memory(
                        memory_id=memory.id,
                        lifecycle_stage="archived",
                        temperature=getattr(memory, "temperature", 50.0),
                    )
                    stats["updated"] += 1
                except Exception as e:  # noqa: BLE001
                    logger.debug("归档更新失败 (%s): %s", memory.id, e)
            else:
                try:
                    memory_manager.update_memory_temperature(
                        memory_id=memory.id,
                        interaction_type="consolidation",
                    )
                    stats["updated"] += 1
                except Exception as e:  # noqa: BLE001
                    logger.debug("温度更新失败 (%s): %s", memory.id, e)
        except Exception as e:  # noqa: BLE001
            logger.warning("写回单条记忆异常: %s", e)

    # 删除已被合并吸收的源记忆（soft，可恢复）
    for sid in source_ids:
        try:
            if memory_manager.forget(sid, soft=True):
                stats["forgotten"] += 1
        except Exception as e:  # noqa: BLE001
            logger.debug("删除源记忆失败 (%s): %s", sid, e)

    logger.info(
        "睡眠整理写回完成: 新增 %s / 删除源 %s / 更新 %s",
        stats["added"], stats["forgotten"], stats["updated"],
    )
    return stats
