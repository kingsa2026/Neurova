"""
PipelineExecutor TDD 测试 - 简化接口的行为测试

测试新的 PipelineExecutor 接口，提供更简洁的 API。
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from neurova.pipeline_executor import PipelineExecutor, PipelineRequest, PipelineResponse


@pytest.fixture
def mock_agent():
    """创建模拟的 Agent 实例"""
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.agent_id = "test-agent"
    agent.config.name = "TestAgent"
    agent.config.tts_enabled = True
    
    # 模拟必要的组件
    agent.session_manager = MagicMock()
    agent.session_manager.get_session = MagicMock(return_value=None)
    agent.session_manager.get_recent_context = MagicMock(return_value=[])
    
    agent.memory_agent = MagicMock()
    agent.memory_agent.add_conversation = AsyncMock()
    
    agent.tts_manager = MagicMock()
    agent.tts_manager.synthesize = AsyncMock(return_value=b"audio bytes")
    agent.tts_manager.is_initialized = True
    
    agent.cognitive_engine = MagicMock()
    agent.cognitive_engine.analyze_conversation = AsyncMock(return_value=0.8)
    
    agent.reflection_logger = MagicMock()
    agent.reflection_logger.log_interaction = AsyncMock()
    
    agent.experience_recorder = MagicMock()
    agent.experience_recorder.record_conversation = AsyncMock()
    
    agent.evocate_manager = MagicMock()
    agent.evocate_manager.generate_from_conversation = AsyncMock()
    
    # 添加必要的属性
    agent._turn_count = 10
    agent._collect_tool_messages = MagicMock(return_value=[])
    agent._save_to_session = MagicMock(return_value="test-session")
    
    return agent


@pytest.fixture
def executor(mock_agent):
    """创建 PipelineExecutor 实例"""
    return PipelineExecutor(mock_agent)


class TestPipelineExecutorBehavior:
    """PipelineExecutor 行为测试 - 简化接口"""
    
    @pytest.mark.asyncio
    async def test_execute_with_simple_request(self, executor, mock_agent):
        """使用简单请求执行管线"""
        request = PipelineRequest(
            user_input="Hello",
            reply="Hi there!",
            session_id="test-session"
        )
        
        response = await executor.execute(request)
        
        assert isinstance(response, PipelineResponse)
        assert response.session_id is not None
        assert response.text == "Hi there!"
    
    @pytest.mark.asyncio
    async def test_execute_with_tts_enabled(self, executor, mock_agent):
        """启用 TTS 时应生成音频"""
        request = PipelineRequest(
            user_input="Hello",
            reply="Hi there!",
            session_id="test-session",
            enable_tts=True
        )
        
        response = await executor.execute(request)
        
        assert response.audio_url is not None
        mock_agent.tts_manager.synthesize.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_with_tts_disabled(self, executor, mock_agent):
        """禁用 TTS 时应跳过音频生成"""
        request = PipelineRequest(
            user_input="Hello",
            reply="Hi there!",
            session_id="test-session",
            enable_tts=False
        )
        
        response = await executor.execute(request)
        
        assert response.audio_url is None
        mock_agent.tts_manager.synthesize.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_execute_with_memory_save(self, executor, mock_agent):
        """启用记忆保存时应保存对话"""
        request = PipelineRequest(
            user_input="Hello",
            reply="Hi there!",
            session_id="test-session",
            save_memory=True
        )
        
        await executor.execute(request)
        
        # 检查记忆保存被调用
        mock_agent._save_to_session.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_without_memory_save(self, executor, mock_agent):
        """禁用记忆保存时应跳过保存"""
        request = PipelineRequest(
            user_input="Hello",
            reply="Hi there!",
            session_id="test-session",
            save_memory=False
        )
        
        await executor.execute(request)
        
        # 检查记忆保存未被调用
        mock_agent._save_to_session.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_execute_handles_error_gracefully(self, executor, mock_agent):
        """处理错误时应优雅降级"""
        mock_agent.tts_manager.synthesize.side_effect = Exception("TTS failed")
        
        request = PipelineRequest(
            user_input="Hello",
            reply="Hi there!",
            session_id="test-session",
            enable_tts=True
        )
        
        response = await executor.execute(request)
        
        # 应返回空音频 URL，而不是崩溃
        assert response.audio_url is None
    
    @pytest.mark.asyncio
    async def test_execute_returns_consistent_structure(self, executor, mock_agent):
        """应始终返回一致的响应结构"""
        request = PipelineRequest(
            user_input="Hello",
            reply="Hi there!",
            session_id="test-session"
        )
        
        response = await executor.execute(request)
        
        # 检查响应结构
        assert hasattr(response, "session_id")
        assert hasattr(response, "text")
        assert hasattr(response, "audio_url")
        assert hasattr(response, "cognitive_score")
        assert hasattr(response, "metadata")


class TestPipelineRequest:
    """PipelineRequest 数据类测试"""
    
    def test_default_values(self):
        """默认值测试"""
        request = PipelineRequest(
            user_input="Hello",
            reply="Hi there!"
        )
        
        assert request.user_input == "Hello"
        assert request.reply == "Hi there!"
        assert request.session_id is None
        assert request.save_memory is True
        assert request.enable_tts is False
        assert request.metadata == {}
    
    def test_custom_values(self):
        """自定义值测试"""
        request = PipelineRequest(
            user_input="Hello",
            reply="Hi there!",
            session_id="custom-session",
            save_memory=False,
            enable_tts=True,
            metadata={"source": "test"}
        )
        
        assert request.session_id == "custom-session"
        assert request.save_memory is False
        assert request.enable_tts is True
        assert request.metadata == {"source": "test"}


class TestPipelineResponse:
    """PipelineResponse 数据类测试"""
    
    def test_response_structure(self):
        """响应结构测试"""
        response = PipelineResponse(
            session_id="test-session",
            text="Hello",
            audio_url=None,
            cognitive_score=0.8,
            metadata={}
        )
        
        assert response.session_id == "test-session"
        assert response.text == "Hello"
        assert response.audio_url is None
        assert response.cognitive_score == 0.8
        assert response.metadata == {}