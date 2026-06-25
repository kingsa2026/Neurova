"""
VoiceMemoryBridge — 语音记忆桥接器

连接语音系统与记忆系统，实现：
1. ASR 结果结构化存储（带情感标签、置信度）
2. TTS 使用统计记录（引擎选择、耗时、成功率）
3. 语音处理→记忆存储→进化学习的完整闭环

设计原则：
- 深模块：小接口（record_asr_result, record_tts_usage），深实现
- 接缝设计：在语音处理与记忆存储之间创建清晰接缝
- 适配器模式：适配 TTSManager/ASRManager 与记忆系统的接口差异
"""

import asyncio
from neurova.core.logger import get_logger
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class VoiceMemoryType(Enum):
    """语音记忆类型"""

    ASR_TRANSCRIPTION = "asr_transcription"  # ASR 转写结果
    TTS_USAGE = "tts_usage"  # TTS 使用统计
    VOICE_EMOTION = "voice_emotion"  # 语音情感分析
    VOICE_FEEDBACK = "voice_feedback"  # 语音反馈


@dataclass
class VoiceMemoryConfig:
    """语音记忆配置"""

    enable_asr_memory: bool = True  # 启用 ASR 记忆存储
    enable_tts_stats: bool = True  # 启用 TTS 使用统计
    enable_emotion_analysis: bool = True  # 启用情感分析
    min_confidence_threshold: float = 0.5  # 最小置信度阈值
    max_memory_age_days: int = 90  # 记忆最大保留天数
    store_audio_metadata: bool = True  # 存储音频元数据
    batch_size: int = 10  # 批量处理大小


@dataclass
class ASRMemoryRecord:
    """ASR 记忆记录"""

    text: str
    confidence: float
    language: str
    engine: str
    duration_ms: int
    timestamp: datetime
    user_id: str
    agent_id: str
    audio_metadata: Optional[Dict[str, Any]] = None
    emotion_label: Optional[str] = None
    emotion_confidence: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "text": self.text,
            "confidence": self.confidence,
            "language": self.language,
            "engine": self.engine,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "audio_metadata": self.audio_metadata or {},
            "emotion_label": self.emotion_label,
            "emotion_confidence": self.emotion_confidence,
            "memory_type": VoiceMemoryType.ASR_TRANSCRIPTION.value,
        }


@dataclass
class TTSUsageStats:
    """TTS 使用统计"""

    text_length: int
    engine: str
    voice: str
    duration_ms: int
    success: bool
    audio_size_bytes: int
    timestamp: datetime
    user_id: str
    agent_id: str
    error: Optional[str] = None
    audio_metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "text_length": self.text_length,
            "engine": self.engine,
            "voice": self.voice,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "audio_size_bytes": self.audio_size_bytes,
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "error": self.error,
            "audio_metadata": self.audio_metadata or {},
            "memory_type": VoiceMemoryType.TTS_USAGE.value,
        }


@dataclass
class VoiceMemoryResult:
    """语音记忆操作结果"""

    success: bool
    memory_id: Optional[str] = None
    emotion_label: Optional[str] = None
    stats_recorded: bool = False
    success_flag: Optional[bool] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class VoiceMemoryBridge:
    """语音记忆桥接器

    深模块：小接口，深实现

    接口：
    - record_asr_result() - 记录 ASR 结果到记忆系统
    - record_tts_usage() - 记录 TTS 使用统计
    - analyze_voice_emotion() - 分析语音情感
    - get_voice_memory_stats() - 获取语音记忆统计

    实现细节：
    - 适配 ASRManager 输出格式到记忆系统格式
    - 适配 TTSManager 输出格式到进化系统格式
    - 集成情感分析模块
    - 提供批量处理能力
    """

    def __init__(
        self,
        config: Optional[VoiceMemoryConfig] = None,
        memory_manager: Optional[Any] = None,
        emotion_module: Optional[Any] = None,
        evolution_orchestrator: Optional[Any] = None,
    ):
        """
        初始化语音记忆桥接器

        Args:
            config: 语音记忆配置
            memory_manager: 记忆管理器实例
            emotion_module: 情感分析模块实例
            evolution_orchestrator: 进化编排器实例
        """
        self.config = config or VoiceMemoryConfig()
        self._memory_manager = memory_manager
        self._emotion_module = emotion_module
        self._evolution_orchestrator = evolution_orchestrator

        # 内部状态
        self._stats_cache: Dict[str, Any] = {}
        self._batch_buffer: List[Dict[str, Any]] = []
        self._last_flush_time: Optional[datetime] = None

        logger.info("VoiceMemoryBridge 初始化完成")

    async def record_asr_result(
        self,
        asr_result: Dict[str, Any],
        user_id: str,
        agent_id: str,
        audio_metadata: Optional[Dict[str, Any]] = None,
    ) -> VoiceMemoryResult:
        """
        记录 ASR 结果到记忆系统

        Args:
            asr_result: ASR 引擎输出结果
                - text: 转写文本
                - confidence: 置信度 (0-1)
                - language: 语言代码
                - engine: 引擎名称
                - duration_ms: 处理时长
            user_id: 用户 ID
            agent_id: Agent ID
            audio_metadata: 音频元数据（可选）

        Returns:
            VoiceMemoryResult: 操作结果
        """
        try:
            # 1. 验证置信度阈值
            confidence = asr_result.get("confidence", 0.0)
            if confidence < self.config.min_confidence_threshold:
                return VoiceMemoryResult(
                    success=False,
                    error=f"Confidence {confidence} below threshold {self.config.min_confidence_threshold}",
                )

            # 2. 创建 ASR 记忆记录
            record = ASRMemoryRecord(
                text=asr_result.get("text", ""),
                confidence=confidence,
                language=asr_result.get("language", "unknown"),
                engine=asr_result.get("engine", "unknown"),
                duration_ms=asr_result.get("duration_ms", 0),
                timestamp=datetime.now(timezone.utc),
                user_id=user_id,
                agent_id=agent_id,
                audio_metadata=audio_metadata,
            )

            # 3. 情感分析（如果启用）
            emotion_label = None
            emotion_state = None
            if self.config.enable_emotion_analysis and self._emotion_module:
                emotion_state = await self.analyze_voice_emotion(record.text, user_id)
                if emotion_state:
                    record.emotion_label = emotion_state.get("primary_emotion", "neutral")
                    record.emotion_confidence = emotion_state.get("confidence", 0.0)
                    emotion_label = record.emotion_label

            # 4. 存储到记忆系统
            memory_id = None
            if self.config.enable_asr_memory and self._memory_manager:
                memory_id = self._memory_manager.remember(
                    content=f"[语音转写] {record.text}",
                    memory_type="asr_transcription",
                    metadata=record.to_dict(),
                )
                logger.debug("ASR 结果已存储到记忆系统: %s", memory_id)

            # 5. 记录到进化系统（P0 修复：ASR → 进化）
            if self._evolution_orchestrator:
                try:
                    self._evolution_orchestrator.on_after_tool_execution(
                        tool_name="asr_transcribe",
                        params={
                            "engine": record.engine,
                            "language": record.language,
                            "confidence": record.confidence,
                            "duration_ms": record.duration_ms,
                            "user_id": user_id,
                            "agent_id": agent_id,
                        },
                        success=True,
                        execution_time=record.duration_ms / 1000.0,
                    )
                    logger.debug(f"ASR 结果已记录到进化系统")
                except Exception as e:
                    logger.warning("ASR 进化记录失败: %s", e)

            # 6. 语音情感 → 进化系统（P2 修复）
            if emotion_state and self._evolution_orchestrator:
                try:
                    self._evolution_orchestrator.on_experience_recorded(
                        text=f"[语音情感] {emotion_state}",
                        task="voice_emotion",
                        tools=["asr_transcribe"],
                        success=True,
                    )
                    logger.debug(f"语音情感已记录到进化系统")
                except Exception as e:
                    logger.warning("语音情感进化记录失败: %s", e)

            return VoiceMemoryResult(
                success=True,
                memory_id=memory_id,
                emotion_label=emotion_label,
                metadata={"record": record.to_dict()},
            )

        except Exception as e:
            logger.error("记录 ASR 结果失败: %s", e)
            return VoiceMemoryResult(
                success=False,
                error=str(e),
            )

    async def record_tts_usage(
        self,
        tts_result: Dict[str, Any],
        user_id: str,
        agent_id: str,
        audio_metadata: Optional[Dict[str, Any]] = None,
    ) -> VoiceMemoryResult:
        """
        记录 TTS 使用统计

        Args:
            tts_result: TTS 引擎输出结果
                - text_length: 文本长度
                - engine: 引擎名称
                - voice: 音色名称
                - duration_ms: 处理时长
                - success: 是否成功
                - audio_size_bytes: 音频大小
                - error: 错误信息（如果失败）
            user_id: 用户 ID
            agent_id: Agent ID
            audio_metadata: 音频元数据（可选）

        Returns:
            VoiceMemoryResult: 操作结果
        """
        try:
            # 1. 创建 TTS 使用统计记录
            stats = TTSUsageStats(
                text_length=tts_result.get("text_length", 0),
                engine=tts_result.get("engine", "unknown"),
                voice=tts_result.get("voice", "default"),
                duration_ms=tts_result.get("duration_ms", 0),
                success=tts_result.get("success", False),
                audio_size_bytes=tts_result.get("audio_size_bytes", 0),
                timestamp=datetime.now(timezone.utc),
                user_id=user_id,
                agent_id=agent_id,
                error=tts_result.get("error"),
                audio_metadata=audio_metadata,
            )

            # 2. 记录到进化系统（如果启用）
            stats_recorded = False
            if self.config.enable_tts_stats and self._evolution_orchestrator:
                try:
                    # 使用 EvolutionOrchestrator 的 on_after_tool_execution 方法
                    # 模拟工具执行：TTS 作为一个工具被调用
                    tool_params = {
                        "text_length": stats.text_length,
                        "engine": stats.engine,
                        "voice": stats.voice,
                        "user_id": user_id,
                        "agent_id": agent_id,
                    }
                    self._evolution_orchestrator.on_after_tool_execution(
                        tool_name="tts_synthesize",
                        params=tool_params,
                        success=stats.success,
                        execution_time=stats.duration_ms / 1000.0,  # 转换为秒
                    )
                    stats_recorded = True
                    logger.debug("TTS 使用统计已记录到进化系统: %s", stats.engine)
                except Exception as e:
                    logger.warning("记录 TTS 使用统计到进化系统失败: %s", e)

            # 3. 存储到记忆系统（可选，用于历史查询）
            memory_id = None
            if self._memory_manager:
                memory_id = self._memory_manager.remember(
                    content=f"[TTS使用] {stats.engine}/{stats.voice} - {'成功' if stats.success else '失败'}",
                    memory_type="tts_usage",
                    metadata=stats.to_dict(),
                )

            return VoiceMemoryResult(
                success=True,
                memory_id=memory_id,
                stats_recorded=stats_recorded,
                success_flag=stats.success,
                metadata={"stats": stats.to_dict()},
            )

        except Exception as e:
            logger.error("记录 TTS 使用统计失败: %s", e)
            return VoiceMemoryResult(
                success=False,
                error=str(e),
            )

    async def analyze_voice_emotion(
        self,
        text: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        分析语音文本情感

        Args:
            text: 转写文本
            user_id: 用户 ID

        Returns:
            情感分析结果字典，包含 primary_emotion 和 confidence
        """
        if not self._emotion_module:
            return None

        try:
            emotion_state = self._emotion_module.analyze_text_emotion(text)
            if emotion_state:
                primary_emotion = getattr(emotion_state, "primary_emotion", None)
                if primary_emotion is not None:
                    primary_emotion = getattr(primary_emotion, "value", "neutral")
                else:
                    primary_emotion = "neutral"
                return {
                    "primary_emotion": primary_emotion,
                    "confidence": getattr(emotion_state, "confidence", 0.0),
                    "secondary_emotions": getattr(emotion_state, "secondary_emotions", {}),
                }
        except Exception as e:
            logger.warning("语音情感分析失败: %s", e)

        return None

    async def get_voice_memory_stats(
        self,
        user_id: str,
        agent_id: str,
        time_range_days: int = 30,
    ) -> Dict[str, Any]:
        """
        获取语音记忆统计

        Args:
            user_id: 用户 ID
            agent_id: Agent ID
            time_range_days: 统计时间范围（天）

        Returns:
            统计信息字典
        """
        stats = {
            "asr_count": 0,
            "tts_count": 0,
            "asr_success_rate": 0.0,
            "tts_success_rate": 0.0,
            "avg_confidence": 0.0,
            "popular_engines": {},
            "time_range_days": time_range_days,
        }

        if not self._memory_manager:
            return stats

        try:
            # 查询 ASR 记忆 - 使用 recall 方法搜索包含 asr_transcription 的记忆
            # recall 返回的是相关记忆列表，我们需要过滤 memory_type
            asr_memories_raw = self._memory_manager.recall(
                query="asr_transcription",
                limit=1000,
            )
            # 过滤出 ASR 类型的记忆（通过 metadata 中的 memory_type 字段）
            asr_memories = [
                mem
                for mem in asr_memories_raw
                if isinstance(mem, dict) and mem.get("metadata", {}).get("memory_type") == "asr_transcription"
            ]

            # 查询 TTS 记忆
            tts_memories_raw = self._memory_manager.recall(
                query="tts_usage",
                limit=1000,
            )
            # 过滤出 TTS 类型的记忆
            tts_memories = [
                mem
                for mem in tts_memories_raw
                if isinstance(mem, dict) and mem.get("metadata", {}).get("memory_type") == "tts_usage"
            ]

            # 统计 ASR 数据
            if asr_memories:
                stats["asr_count"] = len(asr_memories)
                confidences = []
                engines = {}
                for mem in asr_memories:
                    metadata = mem.get("metadata", {})
                    if "confidence" in metadata:
                        confidences.append(metadata["confidence"])
                    engine = metadata.get("engine", "unknown")
                    engines[engine] = engines.get(engine, 0) + 1

                if confidences:
                    stats["avg_confidence"] = sum(confidences) / len(confidences)
                stats["popular_engines"] = engines

            # 统计 TTS 数据
            if tts_memories:
                stats["tts_count"] = len(tts_memories)
                success_count = sum(1 for mem in tts_memories if mem.get("metadata", {}).get("success", False))
                if stats["tts_count"] > 0:
                    stats["tts_success_rate"] = success_count / stats["tts_count"]

            # 计算 ASR 成功率（基于置信度阈值）
            if stats["asr_count"] > 0:
                valid_count = sum(
                    1
                    for mem in asr_memories
                    if mem.get("metadata", {}).get("confidence", 0) >= self.config.min_confidence_threshold
                )
                stats["asr_success_rate"] = valid_count / stats["asr_count"]

        except Exception as e:
            logger.error("获取语音记忆统计失败: %s", e)

        return stats

    async def flush_batch(self) -> int:
        """
        刷新批量缓冲区到存储

        Returns:
            刷新的记录数量
        """
        if not self._batch_buffer:
            return 0

        count = len(self._batch_buffer)
        logger.debug("刷新 %s 条语音记忆到存储", count)

        # 这里可以实现批量写入优化
        # 目前逐条写入
        for record in self._batch_buffer:
            try:
                if record.get("memory_type") == VoiceMemoryType.ASR_TRANSCRIPTION.value:
                    await self.record_asr_result(
                        asr_result=record,
                        user_id=record.get("user_id", ""),
                        agent_id=record.get("agent_id", ""),
                    )
                elif record.get("memory_type") == VoiceMemoryType.TTS_USAGE.value:
                    await self.record_tts_usage(
                        tts_result=record,
                        user_id=record.get("user_id", ""),
                        agent_id=record.get("agent_id", ""),
                    )
            except Exception as e:
                logger.warning("批量刷新记录失败: %s", e)

        self._batch_buffer.clear()
        self._last_flush_time = datetime.now(timezone.utc)

        return count

    def shutdown(self):
        """关闭桥接器，清理资源"""
        logger.info("VoiceMemoryBridge 关闭中...")

        # 刷新剩余缓冲区
        if self._batch_buffer:
            try:
                loop = asyncio.get_running_loop()
                # 在运行的事件循环中调度异步刷新
                loop.create_task(self.flush_batch())
            except RuntimeError:
                # 没有运行的事件循环（同步上下文），同步执行
                try:
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(self.flush_batch())
                    loop.close()
                except Exception as e:
                    logger.warning("同步刷新缓冲区失败: %s", e)

        # 清理引用
        self._memory_manager = None
        self._emotion_module = None
        self._evolution_orchestrator = None

        logger.info("VoiceMemoryBridge 已关闭")


# 工厂函数
def create_voice_memory_bridge(
    config: Optional[VoiceMemoryConfig] = None,
    memory_manager: Optional[Any] = None,
    emotion_module: Optional[Any] = None,
    evolution_orchestrator: Optional[Any] = None,
) -> VoiceMemoryBridge:
    """
    创建语音记忆桥接器实例

    Args:
        config: 语音记忆配置
        memory_manager: 记忆管理器实例
        emotion_module: 情感分析模块实例
        evolution_orchestrator: 进化编排器实例

    Returns:
        VoiceMemoryBridge 实例
    """
    return VoiceMemoryBridge(
        config=config,
        memory_manager=memory_manager,
        emotion_module=emotion_module,
        evolution_orchestrator=evolution_orchestrator,
    )


# 默认单例
_default_bridge: Optional[VoiceMemoryBridge] = None


def get_voice_memory_bridge() -> Optional[VoiceMemoryBridge]:
    """获取默认语音记忆桥接器实例"""
    return _default_bridge


def init_voice_memory_bridge(
    config: Optional[VoiceMemoryConfig] = None,
    memory_manager: Optional[Any] = None,
    emotion_module: Optional[Any] = None,
    evolution_orchestrator: Optional[Any] = None,
) -> VoiceMemoryBridge:
    """
    初始化默认语音记忆桥接器

    Args:
        config: 语音记忆配置
        memory_manager: 记忆管理器实例
        emotion_module: 情感分析模块实例
        evolution_orchestrator: 进化编排器实例

    Returns:
        VoiceMemoryBridge 实例
    """
    global _default_bridge

    _default_bridge = create_voice_memory_bridge(
        config=config,
        memory_manager=memory_manager,
        emotion_module=emotion_module,
        evolution_orchestrator=evolution_orchestrator,
    )

    logger.info("默认 VoiceMemoryBridge 已初始化")
    return _default_bridge


def reset_voice_memory_bridge():
    """重置默认语音记忆桥接器"""
    global _default_bridge

    if _default_bridge:
        _default_bridge.shutdown()

    _default_bridge = None
    logger.info("默认 VoiceMemoryBridge 已重置")
