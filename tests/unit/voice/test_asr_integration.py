"""
ASR 集成测试

测试 ASRManager 与 Agent 的集成
"""

import pytest
from types import SimpleNamespace
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from neurova.asr.base import ASRBase
from neurova.asr.manager import ASRManager, ASRConfig


class MockASR(ASRBase):
    """Mock ASR 引擎用于集成测试"""
    
    def __init__(self, transcribe_result=None):
        super().__init__()
        self._initialized = False
        self._transcribe_result = transcribe_result or {
            "text": "测试转写结果",
            "language": "zh",
            "duration_sec": 1.0,
        }
        
    async def initialize(self) -> bool:
        self._initialized = True
        return True
    
    async def transcribe(self, audio_bytes: bytes, language: str = "zh") -> dict:
        if not self._initialized:
            return {"text": "", "error": "未初始化"}
        return self._transcribe_result
    
    async def shutdown(self) -> None:
        self._initialized = False


class TestASRAgentIntegration:
    """ASR 与 Agent 集成测试"""
    
    @pytest.mark.asyncio
    async def test_asr_manager_in_agent_config(self):
        """测试 AgentConfig 包含 ASR 配置"""
        # 红：测试失败
        from neurova.agent_core import AgentConfig
        
        config = AgentConfig(
            name="test",
            agent_id="test",
            workspace_path="/tmp/test",
            enable_asr=True,
            asr_engine="mock",
            asr_voice="zh",
        )
        
        # 验证 ASR 配置
        assert config.enable_asr is True
        assert config.asr_engine == "mock"
        assert config.asr_voice == "zh"
    
    @pytest.mark.asyncio
    async def test_agent_initializes_asr_manager(self):
        """测试 Agent 初始化 ASR Manager"""
        # 红：测试失败
        from neurova.agent_core import Agent, AgentConfig
        
        config = AgentConfig(
            name="test",
            agent_id="test",
            workspace_path="/tmp/test",
            enable_asr=True,
            asr_engine="mock",
        )
        
        # 使用 mock 避免真实初始化
        with patch('neurova.asr.manager.ASRManager.initialize', return_value=True):
            agent = Agent(config)
            
            # 验证 ASR Manager 已初始化
            assert agent.asr_manager is not None
            assert isinstance(agent.asr_manager, ASRManager)
    
    @pytest.mark.asyncio
    async def test_process_multimodal_calls_asr(self):
        """测试 process_multimodal 调用 ASR"""
        from neurova.agent_core import Agent, AgentConfig
        
        config = AgentConfig(
            name="test",
            agent_id="test",
            workspace_path="/tmp/test",
            enable_asr=True,
            asr_engine="mock",
        )
        
        # 现行契约：process_multimodal 语音走 voice_pipeline.process_asr
        # （agent_core.py:969），不直接调 asr_manager.transcribe
        mock_voice_pipeline = AsyncMock()
        mock_voice_pipeline.process_asr.return_value = SimpleNamespace(
            text="语音识别结果", confidence=0.9, language="zh", emotion=None,
        )
        
        with patch('neurova.agent_core.Agent.chat', new_callable=AsyncMock, return_value="测试回复"):
            agent = Agent(config)
            agent.voice_pipeline = mock_voice_pipeline
            
            # 模拟语音消息
            metadata = {
                "media_type": "voice",
                "audio_bytes": b"test audio data",
                "filename": "test.wav",
            }
            
            result = await agent.process_multimodal(
                content="",
                media_type="voice",
                metadata=metadata,
            )
            
            # 验证语音管线被调用
            mock_voice_pipeline.process_asr.assert_called_once()
            assert "语音识别结果" in result or "测试回复" in result
    
    @pytest.mark.asyncio
    async def test_router_routes_voice_messages(self):
        """测试 Router 路由语音消息"""
        # 红：测试失败
        from neurova.router import MessageRouter, Message, MessageType
        
        # 创建 mock Agent
        mock_agent = AsyncMock()
        mock_agent.process_multimodal.return_value = "语音处理结果"
        
        router = MessageRouter(agent=mock_agent)
        
        # 创建语音消息
        message = Message(
            content="",
            message_type=MessageType.CHAT,
            metadata={
                "media_type": "voice",
                "audio_bytes": b"test audio data",
            },
        )
        
        result = await router.route(message)
        
        # 验证路由成功
        assert result.success is True
        assert result.response == "语音处理结果"
        mock_agent.process_multimodal.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_asr_fallback_on_failure(self):
        """测试 ASR 引擎失败时的 fallback"""
        # 红：测试失败
        config = ASRConfig(
            engine="auto",
            fallback_enabled=True,
        )
        manager = ASRManager(config)
        
        # Mock 第一个引擎失败，第二个成功
        with patch.object(manager, '_initialize_engine') as mock_init:
            mock_init.side_effect = [False, True]
            
            success = await manager.initialize()
            
            # 应该尝试了两个引擎
            assert mock_init.call_count == 2
            assert success is True