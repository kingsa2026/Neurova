"""Agent 关闭逻辑

从 agent_core.py 提取的关闭逻辑，负责清理资源和触发睡眠整理。
"""

from neurova.core.logger import get_logger
from typing import Any, Dict, Optional

logger = get_logger(__name__)


def bind_and_start_sleep_loop(agent) -> None:
    """绑定并启动空闲-睡眠整理触发链。

    断点修复：此前 agent_core 只构造 IdleTimeTracker 并注入
    SleepConsolidation，但从未调用 start() —— 监控线程永不运行，
    空闲阶段永不切换，最完整的"整理+写回"路径是死路。
    """
    tracker = getattr(agent, "idle_tracker", None)
    if tracker is None:
        return
    try:
        if not getattr(tracker, "_monitor_running", False):
            try:
                tracker.initialize()
            except Exception:  # noqa: BLE001 - 已初始化时容忍
                pass
            tracker.start()
        logger.info("Agent %s: 空闲睡眠整理触发链已启动", agent.config.name)
    except Exception as e:
        logger.warning("启动空闲睡眠触发链失败（不影响主流程）: %s", e)


async def shutdown_agent(agent) -> None:
    """Agent 关闭时的清理操作

    触发睡眠整理、刷新缓冲等。

    Args:
        agent: Agent 实例
    """
    logger.info("Agent %s 正在关闭...", agent.config.name)

    # Phase 10: 触发睡眠整理（结果必须写回——此前只打日志，等于无效计算）
    sleep_consolidation = getattr(agent, "sleep_consolidation", None)
    memory_manager = getattr(agent, "memory_manager", None)
    if sleep_consolidation and memory_manager:
        try:
            # 全量记忆（recall("") 语义不明且依赖检索链）
            all_memories = memory_manager.get_all_memories()
            if all_memories:
                from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord

                memory_records = [MemoryRecord.from_dict(m) for m in all_memories]
                result = sleep_consolidation.run_sleep_cycle(memories=memory_records)

                from neurova.cognitive_layers.memory_layer.sleep_writeback import (
                    write_back_consolidation_result,
                )

                stats = write_back_consolidation_result(memory_manager, result)
                logger.info(
                    "关机睡眠整理完成: 处理 %s 条，写回 %s",
                    len(all_memories), stats,
                )
        except Exception as e:
            logger.warning("睡眠整理失败: %s", e)

    # 关闭语音记忆桥接器（刷新缓冲区、清理引用）
    voice_memory_bridge = getattr(agent, "voice_memory_bridge", None)
    if voice_memory_bridge:
        try:
            voice_memory_bridge.shutdown()
            logger.debug("语音记忆桥接器已关闭")
        except Exception as e:
            logger.warning("语音记忆桥接器关闭失败: %s", e)

    # 关闭 TTS 管理器（释放模型资源）
    tts_manager = getattr(agent, "tts_manager", None)
    if tts_manager and hasattr(tts_manager, "shutdown"):
        try:
            await tts_manager.shutdown()
            logger.debug("TTS 管理器已关闭")
        except Exception as e:
            logger.warning("TTS 管理器关闭失败: %s", e)

    # 关闭 ASR 管理器（释放模型资源）
    asr_manager = getattr(agent, "asr_manager", None)
    if asr_manager and hasattr(asr_manager, "shutdown"):
        try:
            await asr_manager.shutdown()
            logger.debug("ASR 管理器已关闭")
        except Exception as e:
            logger.warning("ASR 管理器关闭失败: %s", e)

    # 刷新对话历史缓冲（如果使用 ConversationBuffer）
    conversation_buffer = getattr(agent, "conversation_buffer", None)
    if conversation_buffer and hasattr(conversation_buffer, "flush"):
        try:
            # P2-1 修复: flush() 是同步方法, 返回 List[MemoryItem]。
            # 原实现 `await conversation_buffer.flush()` 对返回的 list 执行 await 抛
            # TypeError 被 except 吞掉, 且已刷出的记忆项被直接丢弃 —— 关闭时对话数据丢失。
            # 现改为同步 flush, 并经记忆写入队列持久化到长期存储。
            items = conversation_buffer.flush()
            if items:
                memory_manager = getattr(agent, "memory_manager", None)
                write_queue = getattr(memory_manager, "_write_queue", None)
                if write_queue is not None and hasattr(write_queue, "enqueue_batch"):
                    write_queue.enqueue_batch(items)
                    written = (
                        write_queue.flush_to_storage()
                        if hasattr(write_queue, "flush_to_storage")
                        else 0
                    )
                    logger.debug(
                        "对话历史缓冲已刷新: %s 项入队, 写入 %s 条", len(items), written
                    )
                else:
                    logger.warning(
                        "记忆写入队列不可用, %s 项缓冲记忆无法持久化", len(items)
                    )
            else:
                logger.debug("对话历史缓冲已刷新（无待处理项）")
        except Exception as e:
            logger.warning("对话历史缓冲刷新失败: %s", e)

    logger.info("Agent %s 已关闭", agent.config.name)
