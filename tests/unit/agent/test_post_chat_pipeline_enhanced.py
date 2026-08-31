"""
PostChatPipeline 增强功能测试

测试依赖注入、步骤状态跟踪、降级处理等功能。
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import tempfile

from neurova.post_chat_pipeline import PostChatPipeline, StepStatus, StepResult


@pytest.fixture
def mock_agent():
    """创建模拟的 Agent 实例"""
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.agent_id = "test-agent"
    agent.config.name = "TestAgent"
    agent.config.enable_tts = False
    agent.config.attachment_dir = tempfile.mkdtemp()
    
    # 模拟必要的组件
    agent.session_manager = MagicMock()
    agent.session_manager.get_session = MagicMock(return_value=None)
    
    agent.memory_agent = MagicMock()
    agent.memory_agent.add_conversation = AsyncMock()
    
    agent.tts_manager = MagicMock()
    agent.tts_manager.synthesize = AsyncMock(return_value=b"audio bytes")
    agent.tts_manager.is_initialized = True
    
    # 添加语音管线模拟
    agent.voice_pipeline = MagicMock()
    agent.voice_pipeline.process_tts = AsyncMock()

    # P0-D1: 显式禁用 growth_analyzer，避免 MagicMock 隐式返回 truthy
    # 让 _step_cognitive_analysis 走 SKIPPED 分支返回默认 0.75
    agent.growth_analyzer = None

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


class TestPostChatPipelineConfiguration:
    """测试依赖注入配置"""
    
    def test_configure_sets_dependencies(self, pipeline):
        """测试 configure 方法设置依赖"""
        mock_memory = MagicMock()
        mock_buffer = MagicMock()
        mock_tts = MagicMock()
        
        pipeline.configure(
            memory_manager=mock_memory,
            conversation_buffer=mock_buffer,
            tts_manager=mock_tts,
        )
        
        assert pipeline._memory_manager == mock_memory
        assert pipeline._conversation_buffer == mock_buffer
        assert pipeline._tts_manager == mock_tts
    
    def test_get_dependency_prioritizes_configured(self, pipeline):
        """测试 _get_dependency 优先使用配置的依赖"""
        mock_memory = MagicMock()
        pipeline.configure(memory_manager=mock_memory)
        
        # 应该返回配置的依赖
        assert pipeline._get_dependency("memory_manager") == mock_memory
    
    def test_get_dependency_fallback_to_agent(self, pipeline, mock_agent):
        """测试 _get_dependency 降级到 agent_ref"""
        # 不配置任何依赖
        mock_agent.memory_manager = MagicMock()
        
        # 应该返回 agent 的依赖
        assert pipeline._get_dependency("memory_manager") == mock_agent.memory_manager
    
    def test_configure_logs_dependencies(self, pipeline, caplog):
        """测试 configure 方法记录依赖状态"""
        import logging
        with caplog.at_level(logging.INFO):
            pipeline.configure(
                memory_manager=MagicMock(),
                tts_manager=MagicMock(),
            )
        
        assert "PostChatPipeline dependencies configured" in caplog.text


class TestPostChatPipelineStepStatus:
    """测试步骤状态跟踪"""
    
    @pytest.mark.asyncio
    async def test_step_results_cleared_on_process(self, pipeline, mock_agent):
        """测试 process 方法开始时清空步骤结果"""
        # 预先添加一些步骤结果
        pipeline._step_results.append(StepResult(
            step_name="test",
            status=StepStatus.EXECUTED,
        ))
        
        await pipeline.process(
            user_input="test",
            reply="test",
            session_id="test",
            save_memory=False,
            enable_tts=False,
            metadata={},
        )
        
        # 应该清空旧结果，添加新结果
        assert len(pipeline._step_results) > 0
        assert pipeline._step_results[0].step_name != "test"
    
    @pytest.mark.asyncio
    async def test_step_save_session_skipped_when_no_save(self, pipeline, mock_agent):
        """测试当 save_memory=False 时跳过 session 保存"""
        result = await pipeline.process(
            user_input="test",
            reply="test",
            session_id="test",
            save_memory=False,
            enable_tts=False,
            metadata={},
        )
        
        # 查找 save_session 步骤
        save_session_results = [r for r in pipeline._step_results if r.step_name == "save_session"]
        assert len(save_session_results) == 1
        assert save_session_results[0].status == StepStatus.SKIPPED
    
    @pytest.mark.asyncio
    async def test_step_save_session_executed_when_save_enabled(self, pipeline, mock_agent):
        """测试当 save_memory=True 时执行 session 保存"""
        result = await pipeline.process(
            user_input="test",
            reply="test",
            session_id="test",
            save_memory=True,
            enable_tts=False,
            metadata={},
        )
        
        # 查找 save_session 步骤
        save_session_results = [r for r in pipeline._step_results if r.step_name == "save_session"]
        assert len(save_session_results) == 1
        assert save_session_results[0].status == StepStatus.EXECUTED
    
    @pytest.mark.asyncio
    async def test_step_cognitive_analysis_skipped_when_no_analyzer(self, pipeline, mock_agent):
        """测试当 growth_analyzer 不可用时跳过认知分析"""
        # 确保 agent 上没有 growth_analyzer 属性，使 _get_dependency 降级返回 None
        if hasattr(mock_agent, 'growth_analyzer'):
            del mock_agent.growth_analyzer
        # 同时确保 pipeline 中也没有配置
        pipeline._growth_analyzer = None
        
        result = await pipeline.process(
            user_input="test",
            reply="test",
            session_id="test",
            save_memory=False,
            enable_tts=False,
            metadata={},
        )
        
        # 查找 cognitive_analysis 步骤
        cognitive_results = [r for r in pipeline._step_results if r.step_name == "cognitive_analysis"]
        assert len(cognitive_results) == 1
        assert cognitive_results[0].status == StepStatus.SKIPPED
        assert cognitive_results[0].data.get("score") == 0.75  # 默认分数


class TestPostChatPipelineStepExecution:
    """测试步骤执行"""
    
    @pytest.mark.asyncio
    async def test_step_save_memory_with_buffer(self, pipeline, mock_agent):
        """测试使用对话缓冲区保存记忆"""
        mock_buffer = MagicMock()
        pipeline.configure(conversation_buffer=mock_buffer)
        
        result = await pipeline.process(
            user_input="test",
            reply="test",
            session_id="test",
            save_memory=True,
            enable_tts=False,
            metadata={},
        )
        
        # 查找 save_memory 步骤
        save_memory_results = [r for r in pipeline._step_results if r.step_name == "save_memory"]
        assert len(save_memory_results) == 1
        assert save_memory_results[0].status == StepStatus.EXECUTED
        
        # 验证缓冲区被调用
        mock_buffer.add_user_message.assert_called_once()
        mock_buffer.add_agent_message.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_step_save_memory_skipped_when_no_dependencies(self, pipeline, mock_agent):
        """测试当没有记忆管理器或缓冲区时跳过记忆保存"""
        # 确保没有 memory_manager 和 conversation_buffer
        if hasattr(mock_agent, 'memory_manager'):
            del mock_agent.memory_manager
        if hasattr(mock_agent, 'conversation_buffer'):
            del mock_agent.conversation_buffer
        
        result = await pipeline.process(
            user_input="test",
            reply="test",
            session_id="test",
            save_memory=True,
            enable_tts=False,
            metadata={},
        )
        
        # 查找 save_memory 步骤
        save_memory_results = [r for r in pipeline._step_results if r.step_name == "save_memory"]
        assert len(save_memory_results) == 1
        assert save_memory_results[0].status == StepStatus.SKIPPED


class TestPostChatPipelineErrorHandling:
    """测试错误处理"""
    
    @pytest.mark.asyncio
    async def test_step_handles_exception_gracefully(self, pipeline, mock_agent):
        """测试步骤优雅地处理异常"""
        # 模拟 _save_to_session 抛出异常
        mock_agent._save_to_session.side_effect = Exception("Test error")
        
        result = await pipeline.process(
            user_input="test",
            reply="test",
            session_id="test",
            save_memory=True,
            enable_tts=False,
            metadata={},
        )
        
        # 查找 save_session 步骤
        save_session_results = [r for r in pipeline._step_results if r.step_name == "save_session"]
        assert len(save_session_results) == 1
        assert save_session_results[0].status == StepStatus.FAILED
        assert "Test error" in save_session_results[0].message
    
    @pytest.mark.asyncio
    async def test_pipeline_returns_consistent_structure(self, pipeline, mock_agent):
        """测试管线始终返回一致的结构"""
        result = await pipeline.process(
            user_input="test",
            reply="test",
            session_id="test",
            save_memory=False,
            enable_tts=False,
            metadata={},
        )
        
        # 检查必需字段
        required_fields = ["actual_session_id", "audio_path", "audio_data", "cognitive_score"]
        for field in required_fields:
            assert field in result, f"缺少必需字段: {field}"


class TestPostChatPipelineIntegration:
    """集成测试"""
    
    @pytest.mark.asyncio
    async def test_full_pipeline_with_all_dependencies(self, pipeline, mock_agent):
        """测试配置所有依赖的完整管线"""
        # 配置所有依赖
        mock_memory = MagicMock()
        mock_memory.remember = MagicMock(return_value="memory-id")
        mock_buffer = MagicMock()
        mock_tts = MagicMock()
        mock_tts.synthesize = AsyncMock(return_value=b"audio data")
        mock_tts.is_initialized = True
        
        # 创建模拟的 voice_pipeline
        mock_voice_pipeline = MagicMock()
        mock_voice_pipeline.process_tts = AsyncMock()
        
        # 模拟 VoicePipelineResult
        from neurova.voice_pipeline import VoicePipelineResult
        mock_result = VoicePipelineResult(
            audio_data=b"audio data",
            tts_engine="mock_tts",
            tts_voice="default",
            tts_duration_ms=100,
            context_injected=False,
            memory_recorded=True,
        )
        mock_voice_pipeline.process_tts.return_value = mock_result
        
        pipeline.configure(
            memory_manager=mock_memory,
            conversation_buffer=mock_buffer,
            tts_manager=mock_tts,
            voice_pipeline=mock_voice_pipeline,
        )
        
        # 需要启用 config.enable_tts，否则 TTS 步骤会被跳过
        mock_agent.config.enable_tts = True
        
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
        mock_buffer.add_user_message.assert_called()
        mock_buffer.add_agent_message.assert_called()
        mock_voice_pipeline.process_tts.assert_called()
        
        # 验证返回结构
        assert result["actual_session_id"] is not None
        assert result["cognitive_score"] == 0.75  # 默认分数
        
        # 验证步骤结果
        executed_steps = [r for r in pipeline._step_results if r.status == StepStatus.EXECUTED]
        skipped_steps = [r for r in pipeline._step_results if r.status == StepStatus.SKIPPED]
        
        # 至少应该有一些步骤被执行
        assert len(executed_steps) > 0
        
        # 打印步骤统计
        print(f"执行步骤: {len(executed_steps)}")
        print(f"跳过步骤: {len(skipped_steps)}")
        for result in pipeline._step_results:
            print(f"  {result.step_name}: {result.status.value} - {result.message[:50]}")
    
    @pytest.mark.asyncio
    async def test_pipeline_step_results_available(self, pipeline, mock_agent):
        """测试步骤结果在 process 后可用"""
        await pipeline.process(
            user_input="test",
            reply="test",
            session_id="test",
            save_memory=False,
            enable_tts=False,
            metadata={},
        )
        
        # 验证步骤结果可用
        assert len(pipeline._step_results) > 0
        
        # 验证每个步骤结果有必要的字段
        for result in pipeline._step_results:
            assert hasattr(result, 'step_name')
            assert hasattr(result, 'status')
            assert hasattr(result, 'message')
            assert hasattr(result, 'duration_ms')
            assert hasattr(result, 'data')
            assert isinstance(result.status, StepStatus)
    
    @pytest.mark.asyncio
    async def test_tts_step_skipped_when_no_voice_pipeline(self, pipeline, mock_agent):
        """测试当 voice_pipeline 不可用时跳过 TTS 步骤"""
        # 配置 TTS 启用但 voice_pipeline 不可用
        mock_agent.config.enable_tts = True
        pipeline._voice_pipeline = None
        
        # 同时确保 agent 上也没有 voice_pipeline
        if hasattr(mock_agent, 'voice_pipeline'):
            del mock_agent.voice_pipeline
        
        result = await pipeline.process(
            user_input="test",
            reply="test",
            session_id="test",
            save_memory=False,
            enable_tts=True,
            metadata={},
        )
        
        # 查找 generate_tts 步骤
        tts_results = [r for r in pipeline._step_results if r.step_name == "generate_tts"]
        assert len(tts_results) == 1
        assert tts_results[0].status == StepStatus.SKIPPED
        assert "voice_pipeline not available" in tts_results[0].message
