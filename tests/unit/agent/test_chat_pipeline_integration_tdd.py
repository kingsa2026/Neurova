"""
ChatPipeline 集成测试 - PipelineExecutor 集成

测试将 PipelineExecutor 集成到 ChatPipeline 中的行为。
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from neurova.agent.chat_pipeline import ChatPipeline, ChatContext
from neurova.pipeline_executor import PipelineExecutor, PipelineRequest, PipelineResponse


@pytest.fixture
def mock_agent():
    """创建模拟的 Agent 实例"""
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.agent_id = "test-agent"
    agent.config.llm_config = MagicMock()
    agent.config.llm_config.model = "test-model"
    agent.config.name = "TestAgent"
    agent.config.tts_enabled = True

    # 记忆模块
    agent.memory_agent = MagicMock()
    agent.memory_agent.update_history = MagicMock()
    agent.memory_agent.moe_retrieve = MagicMock(return_value=[])

    # 上下文构建
    agent.context_orchestrator = MagicMock()
    agent.context_orchestrator.build_context = AsyncMock(return_value=[
        {"role": "system", "content": "test"},
        {"role": "user", "content": "hello"},
    ])
    agent.context_orchestrator.build_tools_for_llm = AsyncMock(return_value=[])

    # 工具执行
    agent.tool_executor = MagicMock()
    agent.tool_executor.execute_text_tool_calls = AsyncMock(side_effect=lambda r, u: r)
    agent.tool_executor.execute_from_memory_async = AsyncMock(return_value={"status": "success"})

    # 新的 PipelineExecutor
    agent.pipeline_executor = MagicMock(spec=PipelineExecutor)
    agent.pipeline_executor.execute = AsyncMock(return_value=PipelineResponse(
        session_id="test-session",
        text="Hello from pipeline!",
        audio_url="/audio/test.wav",
        cognitive_score=0.8,
        metadata={"test": True}
    ))

    # 旧的 post_chat_pipeline (保留用于兼容性)
    agent.post_chat_pipeline = MagicMock()
    agent.post_chat_pipeline.process = AsyncMock(return_value={
        "actual_session_id": "test-session",
        "audio_path": "/audio/test.wav",
        "audio_data": b"audio bytes",
        "cognitive_score": 0.8,
    })

    # 轨迹记录
    agent._trajectory_recorder = None
    agent._current_reasoning = None
    agent._tool_messages_list = []
    agent._current_user_input = None
    agent._turn_count = 0

    # 子系统
    agent.tool_memory = None
    agent.skill_manager = None
    agent.tool_synthesizer = None
    agent.unified_retriever = None
    agent.crystallizer = None
    agent.trace_manager = None
    agent.neuHebb_manager = None
    agent.idle_tracker = MagicMock()
    agent.session_manager = MagicMock()
    agent.loop = None
    agent.llm_client = MagicMock()
    agent.llm_client.config = MagicMock()
    agent.llm_client.config.max_tokens = 8192

    # Agent Loop
    agent._chat_normal = AsyncMock(return_value="Hello from legacy!")
    agent._chat_stream = AsyncMock(return_value="Hello from stream!")

    return agent


@pytest.fixture
def pipeline(mock_agent):
    """创建 ChatPipeline 实例"""
    return ChatPipeline(mock_agent)


@pytest.fixture
def ctx():
    """创建 ChatContext 实例"""
    return ChatContext(user_input="Hello, how are you?")


class TestChatPipelineWithPipelineExecutor:
    """ChatPipeline 与 PipelineExecutor 集成测试"""
    
    @pytest.mark.asyncio
    async def test_uses_pipeline_executor_when_available(self, pipeline, ctx, mock_agent):
        """当 pipeline_executor 可用时，应使用它"""
        result = await pipeline.execute(ctx)
        
        # 应调用 pipeline_executor.execute
        mock_agent.pipeline_executor.execute.assert_called_once()
        
        # 应使用旧的 post_chat_pipeline
        mock_agent.post_chat_pipeline.process.assert_not_called()
        
        # 结果应包含 pipeline_executor 返回的数据
        # 注意：ctx.reply 是在 _step_llm_call 中设置的，不是从 pipeline_executor 返回的
        assert result["audio_path"] == "/audio/test.wav"
        assert result["cognitive_score"] == 0.8
    
    @pytest.mark.asyncio
    async def test_falls_back_to_post_chat_pipeline(self, pipeline, ctx, mock_agent):
        """当 pipeline_executor 不可用时，应 fallback 到 post_chat_pipeline"""
        mock_agent.pipeline_executor = None
        
        result = await pipeline.execute(ctx)
        
        # 应调用 post_chat_pipeline.process
        mock_agent.post_chat_pipeline.process.assert_called_once()
        
        # 结果应包含 post_chat_pipeline 返回的数据
        assert result["text"] == "Hello from legacy!"
    
    @pytest.mark.asyncio
    async def test_creates_pipeline_request_correctly(self, pipeline, ctx, mock_agent):
        """应正确创建 PipelineRequest"""
        ctx.session_id = "custom-session"
        ctx.save_memory = False
        ctx.enable_tts = True
        
        await pipeline.execute(ctx)
        
        # 获取调用参数
        call_args = mock_agent.pipeline_executor.execute.call_args
        request = call_args[0][0]  # 第一个位置参数
        
        assert isinstance(request, PipelineRequest)
        assert request.user_input == "Hello, how are you?"
        assert request.session_id == "custom-session"
        assert request.save_memory is False
        assert request.enable_tts is True
    
    @pytest.mark.asyncio
    async def test_handles_pipeline_executor_error(self, pipeline, ctx, mock_agent):
        """当 pipeline_executor 执行失败时，应 fallback 到 post_chat_pipeline"""
        mock_agent.pipeline_executor.execute.side_effect = Exception("Pipeline failed")
        
        result = await pipeline.execute(ctx)
        
        # 应 fallback 到 post_chat_pipeline
        mock_agent.post_chat_pipeline.process.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_result_structure_matches_original(self, pipeline, ctx, mock_agent):
        """结果结构应与原始结构兼容"""
        result = await pipeline.execute(ctx)
        
        # 检查必需的字段
        assert "text" in result
        assert "audio_path" in result
        assert "audio_data" in result
        
        # 检查 audio_data 从 PipelineResponse.metadata 中提取
        assert result["audio_data"] == mock_agent.pipeline_executor.execute.return_value.metadata.get("audio_data")


class TestChatContextWithPipelineExecutor:
    """ChatContext 与 PipelineExecutor 集成测试"""
    
    def test_context_has_enable_tts_field(self):
        """ChatContext 应有 enable_tts 字段"""
        ctx = ChatContext(user_input="test", enable_tts=True)
        assert ctx.enable_tts is True
    
    def test_context_default_enable_tts(self):
        """ChatContext 默认 enable_tts 应为 False"""
        ctx = ChatContext(user_input="test")
        assert ctx.enable_tts is False