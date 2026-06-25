"""Agent 关闭逻辑

从 agent_core.py 提取的关闭逻辑，负责清理资源和触发睡眠整理。
"""

from neurova.core.logger import get_logger
from typing import Any, Dict, Optional

logger = get_logger(__name__)


async def shutdown_agent(agent) -> None:
    """Agent 关闭时的清理操作

    触发睡眠整理、刷新缓冲等。

    Args:
        agent: Agent 实例
    """
    logger.info("Agent %s 正在关闭...", agent.config.name)

    # Phase 10: 触发睡眠整理
    sleep_consolidation = getattr(agent, "sleep_consolidation", None)
    if sleep_consolidation and agent.memory_manager:
        try:
            # 获取所有记忆进行整理
            all_memories = agent.memory_manager.recall(query="", limit=1000)
            if all_memories:
                # 转换Dict为MemoryRecord
                from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord

                memory_records = [MemoryRecord.from_dict(m) for m in all_memories]
                result = sleep_consolidation.run_sleep_cycle(memories=memory_records)
                logger.info("睡眠整理完成: %s", result)
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
            await conversation_buffer.flush()
            logger.debug("对话历史缓冲已刷新")
        except Exception as e:
            logger.warning("对话历史缓冲刷新失败: %s", e)

    logger.info("Agent %s 已关闭", agent.config.name)
