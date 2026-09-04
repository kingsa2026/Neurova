"""
PipelineExecutor — 简化的对话后处理管线

提供更简洁的接口，隐藏复杂的内部实现。
遵循深度模块原则：小接口，深实现。
"""

from neurova.core.logger import get_logger
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = get_logger(__name__)


@dataclass
class PipelineRequest:
    """管线请求 - 简化接口"""

    user_input: str
    reply: str
    session_id: Optional[str] = None
    save_memory: bool = True
    enable_tts: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    writer_claim: Optional[Any] = None  # P1-10 写入围栏凭证（可选）


@dataclass
class PipelineResponse:
    """管线响应 - 统一结构"""

    session_id: str
    text: str
    audio_url: Optional[str] = None
    cognitive_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class PipelineExecutor:
    """对话后处理管线执行器

    提供简洁的接口，隐藏复杂的内部实现。
    """

    def __init__(self, agent_ref):
        self._agent = agent_ref
        self._pipeline = None  # 延迟加载 PostChatPipeline

    @property
    def _agt(self):
        return self._agent

    async def execute(self, request: PipelineRequest) -> PipelineResponse:
        """执行对话后处理管线

        Args:
            request: 简化的管线请求

        Returns:
            统一的管线响应
        """
        try:
            # 延迟加载 PostChatPipeline
            if self._pipeline is None:
                from neurova.post_chat_pipeline import PostChatPipeline

                self._pipeline = PostChatPipeline(self._agent)

            # 转换请求格式
            result = await self._pipeline.process(
                user_input=request.user_input,
                reply=request.reply,
                session_id=request.session_id,
                save_memory=request.save_memory,
                enable_tts=request.enable_tts,
                metadata=request.metadata,
                writer_claim=request.writer_claim,
            )

            # 构建响应
            response = PipelineResponse(
                session_id=result.get("actual_session_id", request.session_id or "default"),
                text=request.reply,
                audio_url=result.get("audio_path"),
                cognitive_score=result.get("cognitive_score", 0.0),
                metadata={"audio_data": result.get("audio_data"), "original_metadata": request.metadata},
            )

            return response

        except Exception as e:
            logger.warning("管线执行失败: %s", e)
            # 返回降级响应
            return PipelineResponse(
                session_id=request.session_id or "default",
                text=request.reply,
                audio_url=None,
                cognitive_score=0.0,
                metadata={"error": str(e)},
            )

    async def execute_simple(
        self,
        user_input: str,
        reply: str,
        session_id: Optional[str] = None,
        enable_tts: bool = False,
        save_memory: bool = True,
    ) -> PipelineResponse:
        """简化的执行接口

        Args:
            user_input: 用户输入
            reply: Agent 回复
            session_id: 会话 ID
            enable_tts: 是否启用 TTS
            save_memory: 是否保存记忆

        Returns:
            统一的管线响应
        """
        request = PipelineRequest(
            user_input=user_input, reply=reply, session_id=session_id, enable_tts=enable_tts, save_memory=save_memory
        )

        return await self.execute(request)
