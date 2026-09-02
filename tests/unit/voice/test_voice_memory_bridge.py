"""
VoiceMemoryBridge 测试套件

测试语音系统与记忆系统的闭环集成：
1. ASR 结果结构化存储（带情感标签、置信度）
2. TTS 使用统计记录（引擎选择、耗时、成功率）
3. 语音处理→记忆存储→进化学习的完整闭环
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timezone
from typing import Dict, Any, Optional

# 导入被测模块
try:
    from neurova.voice_memory_bridge import (
        VoiceMemoryBridge,
        VoiceMemoryConfig,
        ASRMemoryRecord,
        TTSUsageStats,
        VoiceMemoryResult,
    )
except ImportError:
    # 如果模块不存在，跳过测试
    pytest.skip("voice_memory_bridge 模块不存在", allow_module_level=True)


class TestVoiceMemoryBridge:
    """VoiceMemoryBridge 核心功能测试"""
    
    @pytest.fixture
    def mock_memory_manager(self):
        """模拟记忆管理器"""
        manager = Mock()
        manager.remember = Mock(return_value="memory_123")
        manager.get_memories_by_type = Mock(return_value=[])
        return manager
    
    @pytest.fixture
    def mock_emotion_module(self):
        """模拟情感模块"""
        module = Mock()
        module.analyze_text_emotion = Mock(return_value=Mock(
            primary_emotion=Mock(value="neutral"),
            confidence=0.8,
            secondary_emotions={}
        ))
        return module
    
    @pytest.fixture
    def mock_evolution_orchestrator(self):
        """模拟进化编排器"""
        orchestrator = Mock()
        orchestrator.record_voice_usage = Mock()
        return orchestrator
    
    @pytest.fixture
    def bridge(self, mock_memory_manager, mock_emotion_module, mock_evolution_orchestrator):
        """创建 VoiceMemoryBridge 实例"""
        config = VoiceMemoryConfig(
            enable_asr_memory=True,
            enable_tts_stats=True,
            enable_emotion_analysis=True,
            min_confidence_threshold=0.5,
        )
        return VoiceMemoryBridge(
            config=config,
            memory_manager=mock_memory_manager,
            emotion_module=mock_emotion_module,
            evolution_orchestrator=mock_evolution_orchestrator,
        )
    
    def test_bridge_initialization(self, bridge):
        """测试桥接器初始化"""
        assert bridge is not None
        assert bridge.config.enable_asr_memory is True
        assert bridge.config.enable_tts_stats is True
        assert bridge.config.enable_emotion_analysis is True
    
    def test_asr_memory_record_creation(self):
        """测试 ASR 记忆记录创建"""
        record = ASRMemoryRecord(
            text="你好世界",
            confidence=0.95,
            language="zh",
            engine="whisper",
            duration_ms=1500,
            timestamp=datetime.now(timezone.utc),
            user_id="user_123",
            agent_id="agent_456",
        )
        
        assert record.text == "你好世界"
        assert record.confidence == 0.95
        assert record.language == "zh"
        assert record.engine == "whisper"
        assert record.duration_ms == 1500
        assert record.user_id == "user_123"
        assert record.agent_id == "agent_456"
    
    def test_tts_usage_stats_creation(self):
        """测试 TTS 使用统计创建"""
        stats = TTSUsageStats(
            text_length=100,
            engine="edge-tts",
            voice="zh-CN-XiaoxiaoNeural",
            duration_ms=2000,
            success=True,
            audio_size_bytes=32000,
            timestamp=datetime.now(timezone.utc),
            user_id="user_123",
            agent_id="agent_456",
        )
        
        assert stats.text_length == 100
        assert stats.engine == "edge-tts"
        assert stats.voice == "zh-CN-XiaoxiaoNeural"
        assert stats.duration_ms == 2000
        assert stats.success is True
        assert stats.audio_size_bytes == 32000
    
    @pytest.mark.asyncio
    async def test_record_asr_result_success(self, bridge, mock_memory_manager):
        """测试成功记录 ASR 结果"""
        asr_result = {
            "text": "今天天气真好",
            "confidence": 0.92,
            "language": "zh",
            "engine": "whisper",
            "duration_ms": 1200,
        }
        
        result = await bridge.record_asr_result(
            asr_result=asr_result,
            user_id="user_123",
            agent_id="agent_456",
        )
        
        assert result.success is True
        assert result.memory_id == "memory_123"
        assert result.emotion_label == "neutral"
        mock_memory_manager.remember.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_record_asr_result_low_confidence(self, bridge):
        """测试低置信度 ASR 结果被过滤"""
        asr_result = {
            "text": "模糊的语音",
            "confidence": 0.3,  # 低于阈值 0.5
            "language": "zh",
            "engine": "whisper",
            "duration_ms": 1000,
        }
        
        result = await bridge.record_asr_result(
            asr_result=asr_result,
            user_id="user_123",
            agent_id="agent_456",
        )
        
        assert result.success is False
        assert "confidence" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_record_tts_usage_success(self, bridge, mock_evolution_orchestrator):
        """测试成功记录 TTS 使用统计"""
        tts_result = {
            "text_length": 150,
            "engine": "edge-tts",
            "voice": "zh-CN-XiaoxiaoNeural",
            "duration_ms": 1800,
            "success": True,
            "audio_size_bytes": 48000,
        }
        
        result = await bridge.record_tts_usage(
            tts_result=tts_result,
            user_id="user_123",
            agent_id="agent_456",
        )
        
        assert result.success is True
        assert result.stats_recorded is True
        mock_evolution_orchestrator.on_after_tool_execution.assert_called_once()
        call = mock_evolution_orchestrator.on_after_tool_execution.call_args
        assert call.kwargs["tool_name"] == "tts_synthesize"
    
    @pytest.mark.asyncio
    async def test_record_tts_usage_failure(self, bridge):
        """测试记录 TTS 使用失败"""
        tts_result = {
            "text_length": 100,
            "engine": "edge-tts",
            "voice": "zh-CN-XiaoxiaoNeural",
            "duration_ms": 500,
            "success": False,  # 合成失败
            "error": "网络超时",
        }
        
        result = await bridge.record_tts_usage(
            tts_result=tts_result,
            user_id="user_123",
            agent_id="agent_456",
        )
        
        assert result.success is True  # 记录本身成功
        assert result.stats_recorded is True
        assert result.success_flag is False
    
    @pytest.mark.asyncio
    async def test_analyze_voice_emotion(self, bridge, mock_emotion_module):
        """测试语音情感分析"""
        emotion_state = await bridge.analyze_voice_emotion(
            text="我今天非常开心！",
            user_id="user_123",
        )
        
        assert emotion_state is not None
        mock_emotion_module.analyze_text_emotion.assert_called_once_with("我今天非常开心！")
    
    @pytest.mark.asyncio
    async def test_get_voice_memory_stats(self, bridge, mock_memory_manager):
        """测试获取语音记忆统计"""
        # 模拟记忆查询结果 - 按 memory_type 区分返回值
        asr_memories = [
            {"metadata": {"confidence": 0.9, "engine": "whisper"}},
            {"metadata": {"confidence": 0.8, "engine": "funasr"}},
        ]
        tts_memories = [
            {"metadata": {"success": True, "engine": "edge-tts"}},
        ]
        def _recall(query, limit=1000):
            if "asr" in query:
                return [dict(m, metadata={**m["metadata"], "memory_type": "asr_transcription"}) for m in asr_memories]
            return [dict(m, metadata={**m["metadata"], "memory_type": "tts_usage"}) for m in tts_memories]
        mock_memory_manager.recall.side_effect = _recall

        stats = await bridge.get_voice_memory_stats(
            user_id="user_123",
            agent_id="agent_456",
        )
        
        assert stats is not None
        assert "asr_count" in stats
        assert "tts_count" in stats
        assert stats["asr_count"] == 2
        assert stats["tts_count"] == 1
    
    def test_voice_memory_config_defaults(self):
        """测试默认配置"""
        config = VoiceMemoryConfig()
        
        assert config.enable_asr_memory is True
        assert config.enable_tts_stats is True
        assert config.enable_emotion_analysis is True
        assert config.min_confidence_threshold == 0.5
        assert config.max_memory_age_days == 90
    
    def test_voice_memory_result_creation(self):
        """测试结果对象创建"""
        result = VoiceMemoryResult(
            success=True,
            memory_id="mem_123",
            emotion_label="happy",
            stats_recorded=True,
            error=None,
        )
        
        assert result.success is True
        assert result.memory_id == "mem_123"
        assert result.emotion_label == "happy"
        assert result.stats_recorded is True
        assert result.error is None


class TestVoiceMemoryBridgeIntegration:
    """VoiceMemoryBridge 集成测试"""
    
    @pytest.fixture
    def real_bridge(self):
        """创建真实桥接器实例（无外部依赖）"""
        config = VoiceMemoryConfig()
        return VoiceMemoryBridge(config=config)
    
    @pytest.mark.asyncio
    async def test_end_to_end_asr_to_memory(self, real_bridge):
        """测试端到端 ASR 到记忆流程"""
        # 这个测试验证完整流程，但使用 mock 外部依赖
        with patch.object(real_bridge, '_memory_manager') as mock_mm:
            mock_mm.remember = Mock(return_value="memory_e2e")
            
            asr_result = {
                "text": "完整的语音转写测试",
                "confidence": 0.88,
                "language": "zh",
                "engine": "funasr",
                "duration_ms": 2000,
            }
            
            result = await real_bridge.record_asr_result(
                asr_result=asr_result,
                user_id="e2e_user",
                agent_id="e2e_agent",
            )
            
            assert result.success is True
            assert result.memory_id == "memory_e2e"
    
    @pytest.mark.asyncio
    async def test_end_to_end_tts_to_evolution(self, real_bridge):
        """测试端到端 TTS 到进化系统流程"""
        with patch.object(real_bridge, '_evolution_orchestrator') as mock_eo:
            mock_eo.on_after_tool_execution = Mock()
            
            tts_result = {
                "text_length": 200,
                "engine": "moss-nano",
                "voice": "default",
                "duration_ms": 3000,
                "success": True,
                "audio_size_bytes": 64000,
            }
            
            result = await real_bridge.record_tts_usage(
                tts_result=tts_result,
                user_id="e2e_user",
                agent_id="e2e_agent",
            )
            
            assert result.success is True
            assert result.stats_recorded is True
            mock_eo.on_after_tool_execution.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])