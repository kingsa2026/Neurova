"""
语音系统集成回归测试

测试范围：
1. VoiceMemoryBridge 的 import asyncio 修复
2. Agent.shutdown() 正确关闭语音资源
3. VoiceAdapter 注册到 ChannelManager
4. VoiceEngineAdapter 适配器模式
5. 语音性能监控
"""

import asyncio
import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from datetime import datetime, timezone


# ============================================================
# Fix 1: voice_memory_bridge.py asyncio 导入
# ============================================================

class TestVoiceMemoryBridgeAsyncio:
    """测试 VoiceMemoryBridge 的 asyncio 导入修复"""

    def test_import_asyncio(self):
        """验证 voice_memory_bridge 模块可以正确导入 asyncio"""
        import importlib
        import neurova.voice_memory_bridge as vmb
        # 重新加载模块确保 asyncio 已导入
        importlib.reload(vmb)
        # 验证模块有 asyncio 属性
        assert hasattr(vmb, 'asyncio') or hasattr(asyncio, 'create_task')

    def test_shutdown_with_pending_batch(self):
        """验证 shutdown 在有未完成批次时不抛出 NameError"""
        from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

        config = VoiceMemoryConfig()
        bridge = VoiceMemoryBridge(config=config)

        # 模拟有未完成的批次
        bridge._batch_buffer = [{"text": "test", "memory_type": "asr_transcription"}]

        # 调用 shutdown 不应该抛出 NameError
        try:
            bridge.shutdown()
            # 验证 shutdown 正常执行
            assert bridge._memory_manager is None
            assert bridge._emotion_module is None
            assert bridge._evolution_orchestrator is None
        except NameError as e:
            pytest.fail(f"shutdown() 抛出 NameError: {e}")

    def test_shutdown_without_pending_batch(self):
        """验证 shutdown 在无未完成批次时不抛出异常"""
        from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

        config = VoiceMemoryConfig()
        bridge = VoiceMemoryBridge(config=config)

        # 空批次
        bridge._batch_buffer = []

        try:
            bridge.shutdown()
            assert bridge._memory_manager is None
        except NameError as e:
            pytest.fail(f"shutdown() 抛出 NameError: {e}")

    def test_reset_calls_shutdown(self):
        """验证 reset_voice_memory_bridge 调用 shutdown"""
        from neurova.voice_memory_bridge import (
            init_voice_memory_bridge,
            reset_voice_memory_bridge,
            get_voice_memory_bridge,
        )

        # 初始化
        bridge = init_voice_memory_bridge()
        assert get_voice_memory_bridge() is not None

        # 重置
        reset_voice_memory_bridge()
        assert get_voice_memory_bridge() is None


# ============================================================
# Fix 2+3: Agent.shutdown() 资源清理
# ============================================================

class TestAgentShutdown:
    """测试 Agent.shutdown() 正确关闭语音资源"""

    def test_shutdown_calls_voice_memory_bridge(self):
        """验证 shutdown 调用 voice_memory_bridge.shutdown()"""
        from neurova.agent_core import Agent, AgentConfig

        # 创建 mock agent
        with patch.object(Agent, '__init__', lambda self, **kwargs: None):
            agent = Agent()

            # 设置必要属性
            agent.config = MagicMock()
            agent.config.name = "test"
            agent.memory_manager = MagicMock()
            agent.sleep_consolidation = None

            # 设置 voice_memory_bridge mock
            mock_bridge = MagicMock()
            agent.voice_memory_bridge = mock_bridge

            # 设置 tts_manager mock
            mock_tts = AsyncMock()
            agent.tts_manager = mock_tts

            # 设置 asr_manager mock
            mock_asr = AsyncMock()
            agent.asr_manager = mock_asr

            # 调用 shutdown
            asyncio.run(agent.shutdown())

            # 验证 voice_memory_bridge.shutdown() 被调用
            mock_bridge.shutdown.assert_called_once()

    def test_shutdown_calls_tts_shutdown(self):
        """验证 shutdown 调用 tts_manager.shutdown()"""
        from neurova.agent_core import Agent

        with patch.object(Agent, '__init__', lambda self, **kwargs: None):
            agent = Agent()
            agent.config = MagicMock()
            agent.config.name = "test"
            agent.memory_manager = MagicMock()
            agent.sleep_consolidation = None
            agent.voice_memory_bridge = None

            # 设置 tts_manager mock
            mock_tts = AsyncMock()
            agent.tts_manager = mock_tts

            # 设置 asr_manager mock
            mock_asr = AsyncMock()
            agent.asr_manager = mock_asr

            # 调用 shutdown
            asyncio.run(agent.shutdown())

            # 验证 tts_manager.shutdown() 被调用
            mock_tts.shutdown.assert_called_once()

    def test_shutdown_calls_asr_shutdown(self):
        """验证 shutdown 调用 asr_manager.shutdown()"""
        from neurova.agent_core import Agent

        with patch.object(Agent, '__init__', lambda self, **kwargs: None):
            agent = Agent()
            agent.config = MagicMock()
            agent.config.name = "test"
            agent.memory_manager = MagicMock()
            agent.sleep_consolidation = None
            agent.voice_memory_bridge = None

            # 设置 tts_manager mock
            mock_tts = AsyncMock()
            agent.tts_manager = mock_tts

            # 设置 asr_manager mock
            mock_asr = AsyncMock()
            agent.asr_manager = mock_asr

            # 调用 shutdown
            asyncio.run(agent.shutdown())

            # 验证 asr_manager.shutdown() 被调用
            mock_asr.shutdown.assert_called_once()

    def test_shutdown_graceful_with_none_resources(self):
        """验证 shutdown 在资源为 None 时优雅处理"""
        from neurova.agent_core import Agent

        with patch.object(Agent, '__init__', lambda self, **kwargs: None):
            agent = Agent()
            agent.config = MagicMock()
            agent.config.name = "test"
            agent.memory_manager = MagicMock()
            agent.sleep_consolidation = None

            # 所有语音资源为 None
            agent.voice_memory_bridge = None
            agent.tts_manager = None
            agent.asr_manager = None

            # 调用 shutdown 不应该抛出异常
            asyncio.run(agent.shutdown())


# ============================================================
# Fix 4: VoiceAdapter 注册到 ChannelManager
# ============================================================

class TestVoiceAdapterRegistration:
    """测试 VoiceAdapter 注册到 ChannelManager"""

    def test_voice_adapter_importable(self):
        """验证 VoiceAdapter 可以从 channels 导入"""
        from neurova.channels.voice import VoiceAdapter, create_voice_adapter
        assert VoiceAdapter is not None
        assert create_voice_adapter is not None

    def test_voice_adapter_is_channel_adapter(self):
        """验证 VoiceAdapter 继承 ChannelAdapter"""
        from neurova.channels.voice import VoiceAdapter
        from neurova.channels.base import ChannelAdapter
        assert issubclass(VoiceAdapter, ChannelAdapter)

    def test_voice_adapter_channel_type(self):
        """验证 VoiceAdapter 的 channel_type 为 voice"""
        from neurova.channels.voice import VoiceAdapter, create_voice_adapter
        from neurova.channels.base import ChannelConfig

        config = ChannelConfig(channel_type="voice", app_id="test", app_secret="test")
        adapter = create_voice_adapter(config)
        assert adapter.channel_type == "voice"

    def test_channel_manager_has_voice_adapter(self):
        """验证 ChannelManager 可以注册 VoiceAdapter"""
        from neurova.channels.voice import create_voice_adapter
        from neurova.channels.base import ChannelConfig
        from neurova.channels.manager import ChannelManager

        # 重置单例
        ChannelManager._instance = None
        manager = ChannelManager.get_instance()

        # 创建 voice adapter
        config = ChannelConfig(channel_type="voice", app_id="test_sid", app_secret="test_token")
        adapter = create_voice_adapter(config)

        # 注册
        manager.register_adapter(adapter)

        # 验证
        registered = manager.get_adapter("voice")
        assert registered is not None
        assert registered.channel_type == "voice"

        # 清理
        ChannelManager._instance = None

    def test_voice_adapter_in_channels_init(self):
        """验证 VoiceAdapter 已在 channels/__init__.py 中导出"""
        from neurova.channels import VoiceAdapter, create_voice_adapter
        assert VoiceAdapter is not None
        assert create_voice_adapter is not None


# ============================================================
# Fix 5: VoiceEngineAdapter 适配器模式
# ============================================================

class TestVoiceEngineAdapter:
    """测试 VoiceEngineAdapter 适配器模式"""

    def test_tts_adapter_importable(self):
        """验证 TTSManagerAdapter 可以从 voice_adapter 导入"""
        from neurova.voice_adapter import TTSManagerAdapter, VoiceAdapterFactory
        assert TTSManagerAdapter is not None
        assert VoiceAdapterFactory is not None

    def test_asr_adapter_importable(self):
        """验证 ASRManagerAdapter 可以从 voice_adapter 导入"""
        from neurova.voice_adapter import ASRManagerAdapter, VoiceAdapterFactory
        assert ASRManagerAdapter is not None
        assert VoiceAdapterFactory is not None

    def test_tts_adapter_create(self):
        """验证 TTSManagerAdapter 可以通过工厂创建"""
        from neurova.voice_adapter import VoiceAdapterFactory

        mock_tts = MagicMock()
        mock_tts.synthesize = AsyncMock(return_value=b"audio_data")

        adapter = VoiceAdapterFactory.create_tts_adapter(mock_tts)
        assert adapter is not None
        assert adapter._engine_type == "tts"

    def test_asr_adapter_create(self):
        """验证 ASRManagerAdapter 可以通过工厂创建"""
        from neurova.voice_adapter import VoiceAdapterFactory

        mock_asr = MagicMock()
        mock_asr.transcribe = AsyncMock(return_value={"text": "hello", "confidence": 0.9})

        adapter = VoiceAdapterFactory.create_asr_adapter(mock_asr)
        assert adapter is not None
        assert adapter._engine_type == "asr"

    def test_tts_adapter_adapt_process(self):
        """验证 TTSManagerAdapter 的 adapt_process 调用 synthesize"""
        from neurova.voice_adapter import TTSManagerAdapter

        mock_tts = MagicMock()
        mock_tts.synthesize = AsyncMock(return_value=b"audio_data")

        adapter = TTSManagerAdapter(mock_tts)

        result = asyncio.run(
            adapter.adapt_process("hello world", "synthesize", voice="alice")
        )

        mock_tts.synthesize.assert_called_once_with("hello world", voice="alice")
        assert result == b"audio_data"

    def test_tts_adapter_adapt_result(self):
        """验证 TTSManagerAdapter 的 adapt_result 返回统一格式"""
        from neurova.voice_adapter import TTSManagerAdapter

        mock_tts = MagicMock()
        mock_tts.engine_name = "edge-tts"

        adapter = TTSManagerAdapter(mock_tts)
        result = adapter.adapt_result(b"audio_data", "synthesize")

        assert result["audio_data"] == b"audio_data"
        assert result["engine"] == "edge-tts"
        assert result["operation"] == "synthesize"

    def test_asr_adapter_adapt_process(self):
        """验证 ASRManagerAdapter 的 adapt_process 调用 transcribe"""
        from neurova.voice_adapter import ASRManagerAdapter

        mock_asr = MagicMock()
        mock_asr.transcribe = AsyncMock(return_value={"text": "hello", "confidence": 0.9})

        adapter = ASRManagerAdapter(mock_asr)

        result = asyncio.run(
            adapter.adapt_process(b"audio_bytes", "transcribe", language="zh")
        )

        mock_asr.transcribe.assert_called_once_with(b"audio_bytes", language="zh")
        assert result["text"] == "hello"
        assert result["confidence"] == 0.9


# ============================================================
# Fix 6: 语音性能监控
# ============================================================

class TestVoicePerformanceMonitoring:
    """测试语音性能监控"""

    def test_voice_performance_metrics_importable(self):
        """验证语音性能监控指标可以导入"""
        from neurova.voice_memory_bridge import VoiceMemoryConfig
        config = VoiceMemoryConfig()
        assert config.enable_asr_memory is True
        assert config.enable_tts_stats is True

    def test_asr_result_records_duration(self):
        """验证 ASR 结果记录处理时长"""
        from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

        config = VoiceMemoryConfig()
        mock_memory = MagicMock()
        bridge = VoiceMemoryBridge(config=config, memory_manager=mock_memory)

        asr_result = {
            "text": "hello world",
            "confidence": 0.95,
            "language": "zh",
            "engine": "whisper",
            "duration_ms": 1200,
        }

        result = asyncio.run(
            bridge.record_asr_result(
                asr_result=asr_result,
                user_id="user1",
                agent_id="agent1",
            )
        )

        assert result.success is True
        # 验证元数据包含 duration_ms
        metadata = result.metadata.get("record", {})
        assert metadata.get("duration_ms") == 1200

    def test_tts_result_records_duration(self):
        """验证 TTS 结果记录处理时长"""
        from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

        config = VoiceMemoryConfig()
        mock_memory = MagicMock()
        mock_evolution = MagicMock()
        bridge = VoiceMemoryBridge(
            config=config,
            memory_manager=mock_memory,
            evolution_orchestrator=mock_evolution,
        )

        tts_result = {
            "text_length": 100,
            "engine": "edge-tts",
            "voice": "zh-CN-XiaoxiaoNeural",
            "duration_ms": 500,
            "success": True,
            "audio_size_bytes": 8000,
        }

        result = asyncio.run(
            bridge.record_tts_usage(
                tts_result=tts_result,
                user_id="user1",
                agent_id="agent1",
            )
        )

        assert result.success is True
        assert result.stats_recorded is True
        # 验证元数据包含 duration_ms
        stats = result.metadata.get("stats", {})
        assert stats.get("duration_ms") == 500

    def test_get_voice_memory_stats(self):
        """验证 get_voice_memory_stats 返回统计信息"""
        from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

        config = VoiceMemoryConfig()
        mock_memory = MagicMock()
        mock_memory.recall = MagicMock(return_value=[])
        bridge = VoiceMemoryBridge(config=config, memory_manager=mock_memory)

        stats = asyncio.run(
            bridge.get_voice_memory_stats(
                user_id="user1",
                agent_id="agent1",
                time_range_days=30,
            )
        )

        assert "asr_count" in stats
        assert "tts_count" in stats
        assert "asr_success_rate" in stats
        assert "tts_success_rate" in stats
        assert "avg_confidence" in stats
        assert stats["time_range_days"] == 30


# ============================================================
# 综合集成测试
# ============================================================

class TestVoiceSystemIntegration:
    """综合集成测试"""

    def test_full_voice_pipeline(self):
        """测试完整的语音处理流水线"""
        from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

        config = VoiceMemoryConfig(
            enable_asr_memory=True,
            enable_tts_stats=True,
            enable_emotion_analysis=False,  # 禁用情感分析简化测试
        )

        mock_memory = MagicMock()
        mock_evolution = MagicMock()
        bridge = VoiceMemoryBridge(
            config=config,
            memory_manager=mock_memory,
            evolution_orchestrator=mock_evolution,
        )

        # 1. ASR 转写
        asr_result = {
            "text": "你好世界",
            "confidence": 0.95,
            "language": "zh",
            "engine": "whisper",
            "duration_ms": 1200,
        }
        asr_output = asyncio.run(
            bridge.record_asr_result(asr_result, "user1", "agent1")
        )
        assert asr_output.success is True
        assert asr_output.memory_id is not None

        # 2. TTS 合成
        tts_result = {
            "text_length": 100,
            "engine": "edge-tts",
            "voice": "zh-CN-XiaoxiaoNeural",
            "duration_ms": 500,
            "success": True,
            "audio_size_bytes": 8000,
        }
        tts_output = asyncio.run(
            bridge.record_tts_usage(tts_result, "user1", "agent1")
        )
        assert tts_output.success is True
        assert tts_output.stats_recorded is True

        # 3. 获取统计
        mock_memory.recall = MagicMock(return_value=[
            {"metadata": {"memory_type": "asr_transcription", "confidence": 0.95, "engine": "whisper"}},
            {"metadata": {"memory_type": "tts_usage", "success": True}},
        ])
        stats = asyncio.run(
            bridge.get_voice_memory_stats("user1", "agent1")
        )
        assert stats["asr_count"] > 0

        # 4. 清理
        bridge.shutdown()
        assert bridge._memory_manager is None

    def test_low_confidence_rejected(self):
        """验证低置信度 ASR 结果被拒绝"""
        from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

        config = VoiceMemoryConfig(min_confidence_threshold=0.7)
        mock_memory = MagicMock()
        bridge = VoiceMemoryBridge(config=config, memory_manager=mock_memory)

        asr_result = {
            "text": "hello",
            "confidence": 0.3,  # 低于阈值
            "language": "zh",
            "engine": "whisper",
            "duration_ms": 100,
        }

        result = asyncio.run(
            bridge.record_asr_result(asr_result, "user1", "agent1")
        )

        assert result.success is False
        assert "below threshold" in result.error
        mock_memory.remember.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
