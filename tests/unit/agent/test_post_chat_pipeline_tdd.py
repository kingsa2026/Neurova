"""
PostChatPipeline TDD 测试 - 行为测试而非实现测试

遵循 TDD 垂直切片方法，测试用户可观察的行为。
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import tempfile

from neurova.post_chat_pipeline import PostChatPipeline
from neurova.voice_pipeline import VoicePipelineResult


@pytest.fixture
def mock_agent():
    """创建模拟的 Agent 实例"""
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.agent_id = "test-agent"
    agent.config.name = "TestAgent"
    agent.config.tts_enabled = True  # 启用 TTS
    # P0-D1: TTS 写文件需要真实路径，不能让 MagicMock 隐式返回
    agent.config.attachment_dir = tempfile.mkdtemp()
    # P0-D1: _step_generate_tts 检查 config.enable_tts，需要显式 True
    agent.config.enable_tts = True

    # 模拟必要的组件
    agent.session_manager = MagicMock()
    agent.session_manager.get_session = MagicMock(return_value=None)
    agent.session_manager.get_recent_context = MagicMock(return_value=[])

    agent.memory_agent = MagicMock()
    agent.memory_agent.add_conversation = AsyncMock()

    # P0-D1: 实现已迁移到统一 voice_pipeline 路径（_step_generate_tts 调
    # voice_pipeline.process_tts），不再直调 tts_manager.synthesize。
    # 配置 voice_pipeline 返回成功结果，让 TTS 测试走真实成功路径。
    agent.tts_manager = MagicMock()
    agent.tts_manager.synthesize = AsyncMock(return_value=b"audio bytes")
    agent.tts_manager.is_initialized = True

    agent.voice_pipeline = MagicMock()
    agent.voice_pipeline.process_tts = AsyncMock(
        return_value=VoicePipelineResult(
            audio_data=b"audio bytes",
            tts_engine="mock_tts",
            tts_voice="default",
            tts_duration_ms=100,
            context_injected=False,
            memory_recorded=True,
        )
    )

    agent.cognitive_engine = MagicMock()
    agent.cognitive_engine.analyze_conversation = AsyncMock(return_value=0.8)

    # P0-D1: 显式禁用 growth_analyzer，让 _step_cognitive_analysis 走 SKIPPED 分支返回 0.75
    # 否则 MagicMock 隐式返回 truthy，pipeline 会走真实计算路径返回 0.3-1.0 的低分
    agent.growth_analyzer = None

    agent.reflection_logger = MagicMock()
    agent.reflection_logger.log_interaction = AsyncMock()

    agent.experience_recorder = MagicMock()
    agent.experience_recorder.record_conversation = AsyncMock()

    agent.evocate_manager = MagicMock()
    agent.evocate_manager.generate_from_conversation = AsyncMock()

    # 添加 PostChatPipeline 需要的其他属性
    agent._turn_count = 10
    agent.turn_count = 10  # P3-c 收窄：post_chat 经显式 property 读取
    agent._collect_tool_messages = MagicMock(return_value=[])
    agent._save_to_session = MagicMock(return_value="test-session")

    return agent


@pytest.fixture
def pipeline(mock_agent):
    """创建 PostChatPipeline 实例"""
    return PostChatPipeline(mock_agent)


class TestPostChatPipelineBehavior:
    """PostChatPipeline 行为测试 - 用户可观察的行为"""
    
    @pytest.mark.asyncio
    async def test_pipeline_returns_session_id(self, pipeline, mock_agent):
        """管线应返回实际使用的 session_id"""
        result = await pipeline.process(
            user_input="Hello",
            reply="Hi there!",
            session_id=None,  # 无预设 session
            save_memory=True,
            enable_tts=False,
            metadata={}
        )
        
        assert "actual_session_id" in result
        assert result["actual_session_id"] is not None
    
    @pytest.mark.asyncio
    async def test_pipeline_generates_audio_when_enabled(self, pipeline, mock_agent):
        """当启用 TTS 时，管线应生成音频"""
        result = await pipeline.process(
            user_input="Hello",
            reply="Hi there!",
            session_id="test-session",
            save_memory=True,
            enable_tts=True,  # 启用 TTS
            metadata={}
        )
        
        assert "audio_path" in result
        assert result["audio_path"] is not None
        # P0-D1: 实现走统一 voice_pipeline 路径，断言 voice_pipeline.process_tts 被调用
        mock_agent.voice_pipeline.process_tts.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_pipeline_skips_audio_when_disabled(self, pipeline, mock_agent):
        """当禁用 TTS 时，管线应跳过音频生成"""
        result = await pipeline.process(
            user_input="Hello",
            reply="Hi there!",
            session_id="test-session",
            save_memory=True,
            enable_tts=False,  # 禁用 TTS
            metadata={}
        )
        
        assert result["audio_path"] is None
        mock_agent.tts_manager.synthesize.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_pipeline_analyzes_cognitive_score(self, pipeline, mock_agent):
        """管线应分析认知分数"""
        result = await pipeline.process(
            user_input="Hello",
            reply="Hi there!",
            session_id="test-session",
            save_memory=True,
            enable_tts=False,
            metadata={}
        )
        
        assert "cognitive_score" in result
        # 当没有 growth_analyzer 时，默认返回 0.75
        assert result["cognitive_score"] == 0.75
    
    @pytest.mark.asyncio
    async def test_pipeline_saves_memory_when_enabled(self, pipeline, mock_agent):
        """当启用记忆保存时，管线应保存对话记忆"""
        # 添加 conversation_buffer mock
        mock_agent.conversation_buffer = MagicMock()
        mock_agent.conversation_buffer.add_user_message = MagicMock()
        mock_agent.conversation_buffer.add_agent_message = MagicMock()
        
        await pipeline.process(
            user_input="Hello",
            reply="Hi there!",
            session_id="test-session",
            save_memory=True,  # 启用记忆保存
            enable_tts=False,
            metadata={}
        )
        
        # 检查 conversation_buffer 被调用
        mock_agent.conversation_buffer.add_user_message.assert_called_once()
        mock_agent.conversation_buffer.add_agent_message.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_pipeline_skips_memory_when_disabled(self, pipeline, mock_agent):
        """当禁用记忆保存时，管线应跳过记忆保存"""
        await pipeline.process(
            user_input="Hello",
            reply="Hi there!",
            session_id="test-session",
            save_memory=False,  # 禁用记忆保存
            enable_tts=False,
            metadata={}
        )
        
        mock_agent.memory_agent.add_conversation.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_pipeline_handles_tts_failure_gracefully(self, pipeline, mock_agent):
        """当 TTS 失败时，管线应优雅地处理错误"""
        # P0-D1: 实现走统一 voice_pipeline 路径，失败注入到 voice_pipeline.process_tts
        mock_agent.voice_pipeline.process_tts.side_effect = Exception("TTS failed")
        
        result = await pipeline.process(
            user_input="Hello",
            reply="Hi there!",
            session_id="test-session",
            save_memory=True,
            enable_tts=True,
            metadata={}
        )
        
        # 应返回空音频路径，而不是崩溃
        assert result["audio_path"] is None
        assert result["audio_data"] is None
    
    @pytest.mark.asyncio
    async def test_pipeline_returns_consistent_structure(self, pipeline, mock_agent):
        """管线应始终返回一致的结构"""
        result = await pipeline.process(
            user_input="Hello",
            reply="Hi there!",
            session_id="test-session",
            save_memory=True,
            enable_tts=False,
            metadata={}
        )
        
        # 检查必需字段
        required_fields = ["actual_session_id", "audio_path", "audio_data", "cognitive_score"]
        for field in required_fields:
            assert field in result, f"缺少必需字段: {field}"


class TestPostChatPipelineIntegration:
    """PostChatPipeline 集成测试 - 测试完整流程"""
    
    @pytest.mark.asyncio
    async def test_full_pipeline_with_all_features(self, pipeline, mock_agent):
        """完整管线测试 - 所有功能启用"""
        # 添加必要的 mock
        mock_agent.conversation_buffer = MagicMock()
        mock_agent.conversation_buffer.add_user_message = MagicMock()
        mock_agent.conversation_buffer.add_agent_message = MagicMock()
        mock_agent.memory_manager = MagicMock()
        mock_agent.memory_manager.remember = MagicMock(return_value="memory-id")
        
        result = await pipeline.process(
            user_input="你好，今天天气怎么样？",
            reply="今天天气很好，适合外出活动。",
            session_id="test-session",
            save_memory=True,
            enable_tts=True,
            metadata={"source": "test"}
        )
        
        # 验证关键步骤被调用
        mock_agent._save_to_session.assert_called()
        # P0-D1: 实现走统一 voice_pipeline 路径
        mock_agent.voice_pipeline.process_tts.assert_called()
        
        # 验证返回结构
        assert result["actual_session_id"] is not None
        # 默认认知分数为 0.75
        assert result["cognitive_score"] == 0.75
    
    @pytest.mark.asyncio
    async def test_pipeline_performance(self, pipeline, mock_agent):
        """管线性能测试 - 确保在合理时间内完成"""
        import time
        
        start_time = time.time()
        
        await pipeline.process(
            user_input="Performance test",
            reply="Response",
            session_id="perf-session",
            save_memory=True,
            enable_tts=False,
            metadata={}
        )
        
        elapsed_time = time.time() - start_time
        
        # 管线应在 1 秒内完成（无 TTS）
        assert elapsed_time < 1.0, f"管线执行时间过长: {elapsed_time:.2f}秒"