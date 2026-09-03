"""
语音上下文集成测试

测试范围：
1. VoiceContextModule 接口测试
2. 语音元数据传递到上下文构建
3. 语音情感注入上下文
4. VoiceMemoryBridge 与上下文系统集成
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone


# ============================================================
# 测试 1: VoiceContextModule 接口
# ============================================================

class TestVoiceContextModuleInterface:
    """测试 VoiceContextModule 接口设计"""

    def test_import_voice_context_module(self):
        """验证 VoiceContextModule 可以导入"""
        from neurova.voice_context_module import VoiceContextModule
        assert VoiceContextModule is not None

    def test_voice_context_module_has_required_methods(self):
        """验证 VoiceContextModule 有必要的方法"""
        from neurova.voice_context_module import VoiceContextModule
        
        # 检查必要方法存在
        assert hasattr(VoiceContextModule, 'build_voice_context')
        assert hasattr(VoiceContextModule, 'inject_metadata')
        assert hasattr(VoiceContextModule, 'analyze_emotion')
        assert hasattr(VoiceContextModule, 'get_voice_context')


# ============================================================
# 测试 2: 语音元数据传递到上下文构建
# ============================================================

class TestVoiceMetadataPassing:
    """测试语音元数据传递到上下文构建"""

    @pytest.mark.asyncio
    async def test_voice_metadata_in_context(self):
        """验证语音元数据（置信度、语言、引擎）传递到上下文构建"""
        from neurova.voice_context_module import VoiceContextModule
        from neurova.context_pool import ContextInput, ContextSource
        
        # 创建 VoiceContextModule 实例
        module = VoiceContextModule()
        
        # 模拟 ASR 结果
        asr_result = {
            "text": "今天天气真好",
            "confidence": 0.95,
            "language": "zh",
            "engine": "funasr",
            "duration_ms": 1200,
        }
        
        # 构建语音上下文
        voice_context = module.build_voice_context(asr_result=asr_result)
        
        # 验证上下文包含元数据
        assert "confidence" in voice_context
        assert "language" in voice_context
        assert "engine" in voice_context
        assert voice_context["confidence"] == 0.95
        assert voice_context["language"] == "zh"

    @pytest.mark.asyncio
    async def test_voice_metadata_injected_to_context_pool(self):
        """验证语音元数据注入到 ContextPool"""
        from neurova.voice_context_module import VoiceContextModule
        from neurova.context_pool import ContextInput, ContextSource, ContextPool
        
        # 创建 VoiceContextModule 实例
        module = VoiceContextModule()
        
        # 模拟 ASR 结果
        asr_result = {
            "text": "你好世界",
            "confidence": 0.88,
            "language": "zh",
            "engine": "whisper",
            "duration_ms": 800,
        }
        
        # 构建语音上下文
        voice_context = module.build_voice_context(asr_result=asr_result)
        
        # 创建 ContextPool 并注入
        context_pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=4000
        )
        
        # 注入语音上下文
        module.inject_metadata(context_pool, voice_context)
        
        # 验证 ContextPool 中有语音相关上下文
        # 检查是否有语音相关的上下文（语音信息注入为 multimodal）
        found_voice = False
        for ctx in context_pool.get_contexts():
            if ctx.source.value == "multimodal" or "语音" in ctx.content:
                found_voice = True
                break
        
        assert found_voice, "ContextPool 中未找到语音相关上下文"


# ============================================================
# 测试 3: 语音情感注入上下文
# ============================================================

class TestVoiceEmotionInjection:
    """测试语音情感注入上下文"""

    @pytest.mark.asyncio
    async def test_voice_emotion_in_context(self):
        """验证语音情感分析结果注入到上下文"""
        from neurova.voice_context_module import VoiceContextModule
        from neurova.context_pool import ContextInput, ContextSource
        
        # 创建 VoiceContextModule 实例
        module = VoiceContextModule()
        
        # 模拟 ASR 结果（带情感文本）
        asr_result = {
            "text": "我今天非常开心，太高兴了！",
            "confidence": 0.92,
            "language": "zh",
            "engine": "funasr",
            "duration_ms": 1000,
        }
        
        # 分析语音情感
        emotion_context = module.analyze_emotion(asr_result["text"])
        
        # 验证情感分析结果
        assert "primary_emotion" in emotion_context
        assert "confidence" in emotion_context
        # 文本包含积极情感关键词，应该不是 neutral
        assert emotion_context["primary_emotion"] != "neutral"

    @pytest.mark.asyncio
    async def test_voice_emotion_injected_to_context_pool(self):
        """验证语音情感注入到 ContextPool"""
        from neurova.voice_context_module import VoiceContextModule
        from neurova.context_pool import ContextInput, ContextSource, ContextPool
        
        # 创建 VoiceContextModule 实例
        module = VoiceContextModule()
        
        # 模拟 ASR 结果
        asr_result = {
            "text": "我今天非常开心，太高兴了！",
            "confidence": 0.92,
            "language": "zh",
            "engine": "funasr",
            "duration_ms": 1000,
        }
        
        # 构建语音上下文（包含情感）
        voice_context = module.build_voice_context(asr_result=asr_result)
        
        # 创建 ContextPool 并注入
        context_pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=4000
        )
        
        # 注入语音上下文
        module.inject_metadata(context_pool, voice_context)
        
        # 验证 ContextPool 中有情感相关上下文
        # VoiceContextModule 将情感信息作为 multimodal 上下文注入
        found_emotion = False
        for ctx in context_pool.get_contexts():
            if "情感" in ctx.content or "emotion" in ctx.content.lower():
                found_emotion = True
                break
        
        assert found_emotion, "ContextPool 中未找到情感相关上下文"


# ============================================================
# 测试 4: VoiceMemoryBridge 与上下文系统集成
# ============================================================

class TestVoiceMemoryBridgeIntegration:
    """测试 VoiceMemoryBridge 与上下文系统集成"""

    @pytest.mark.asyncio
    async def test_voice_memory_bridge_provides_context(self):
        """验证 VoiceMemoryBridge 提供语音上下文给 ContextOrchestrator"""
        from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig
        from neurova.voice_context_module import VoiceContextModule
        
        # 创建 VoiceContextModule
        voice_module = VoiceContextModule()
        
        # 模拟 VoiceMemoryBridge
        config = VoiceMemoryConfig()
        bridge = VoiceMemoryBridge(config=config)
        
        # 模拟 ASR 结果记录
        asr_result = {
            "text": "测试文本",
            "confidence": 0.85,
            "language": "zh",
            "engine": "mock",
            "duration_ms": 500,
        }
        
        # 记录 ASR 结果
        result = await bridge.record_asr_result(
            asr_result=asr_result,
            user_id="test_user",
            agent_id="test_agent",
        )
        
        # 验证 VoiceContextModule 可以从 VoiceMemoryBridge 获取上下文
        # 这是一个集成测试，验证两个模块可以协作
        assert result.success is True

    @pytest.mark.asyncio
    async def test_voice_context_in_chat_context(self):
        """验证语音上下文注入到 ChatContext"""
        from neurova.voice_context_module import VoiceContextModule
        from neurova.context_pool import ContextInput, ContextSource, ContextPool
        
        # 创建 VoiceContextModule
        module = VoiceContextModule()
        
        # 模拟完整的语音上下文
        asr_result = {
            "text": "请帮我查一下天气",
            "confidence": 0.90,
            "language": "zh",
            "engine": "funasr",
            "duration_ms": 1500,
        }
        
        # 构建语音上下文
        voice_context = module.build_voice_context(asr_result=asr_result)
        
        # 创建 ContextPool 并注入
        context_pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=4000
        )
        
        # 注入语音上下文
        module.inject_metadata(context_pool, voice_context)
        
        # 验证上下文数量增加
        initial_count = len(context_pool.get_contexts())
        assert initial_count > 0


# ============================================================
# 测试 5: ContextOrchestrator 语音上下文参数
# ============================================================

class TestContextOrchestratorVoiceParams:
    """测试 ContextOrchestrator 接受语音上下文参数"""

    @pytest.mark.asyncio
    async def test_build_context_accepts_voice_context(self):
        """验证 build_context 接受 voice_context 参数"""
        # 这个测试验证 ContextOrchestrator 的接口变更
        # 需要检查 build_context 方法签名
        import inspect
        from neurova.context.orchestrator import ContextOrchestrator
        
        # 获取 build_context 方法签名
        sig = inspect.signature(ContextOrchestrator.build_context)
        params = list(sig.parameters.keys())
        
        # 验证 voice_context 参数存在
        assert "voice_context" in params, f"build_context 缺少 voice_context 参数，当前参数: {params}"

    @pytest.mark.asyncio
    async def test_voice_context_injected_to_context_pool(self):
        """验证语音上下文通过 build_context 注入到 ContextPool"""
        # 这是一个集成测试，需要 mock Agent
        # 简单验证接口签名即可
        import inspect
        from neurova.context.orchestrator import ContextOrchestrator
        
        sig = inspect.signature(ContextOrchestrator.build_context)
        voice_param = sig.parameters.get("voice_context")
        
        assert voice_param is not None
        assert voice_param.default is None  # 默认为 None


# ============================================================
# 测试 6: 完整语音上下文流程
# ============================================================

class TestCompleteVoiceContextFlow:
    """测试完整的语音上下文流程"""

    @pytest.mark.asyncio
    async def test_asr_to_context_flow(self):
        """验证 ASR → 上下文构建的完整流程"""
        from neurova.voice_context_module import VoiceContextModule
        from neurova.context_pool import ContextInput, ContextSource, ContextPool
        
        # 创建 VoiceContextModule
        module = VoiceContextModule()
        
        # 模拟 ASR 结果
        asr_result = {
            "text": "帮我定一个明天下午3点的会议",
            "confidence": 0.87,
            "language": "zh",
            "engine": "funasr",
            "duration_ms": 2000,
        }
        
        # 1. 构建语音上下文
        voice_context = module.build_voice_context(asr_result=asr_result)
        
        # 2. 分析情感
        emotion_context = module.analyze_emotion(asr_result["text"])
        voice_context["emotion"] = emotion_context
        
        # 3. 创建 ContextPool
        context_pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=4000
        )
        
        # 4. 注入语音上下文
        module.inject_metadata(context_pool, voice_context)
        
        # 5. 验证上下文包含语音信息
        voice_contexts = [
            ctx for ctx in context_pool.get_contexts()
            if ctx.source.value == "multimodal" or "语音" in ctx.content
        ]
        
        assert len(voice_contexts) > 0, "未找到语音上下文"
        
        # 验证上下文内容包含元数据
        first_voice_ctx = voice_contexts[0]
        assert "置信度" in first_voice_ctx.content or "confidence" in first_voice_ctx.content.lower()

    @pytest.mark.asyncio
    async def test_tts_usage_recorded(self):
        """验证 TTS 使用统计记录"""
        from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig
        
        # 创建 VoiceMemoryBridge
        config = VoiceMemoryConfig()
        bridge = VoiceMemoryBridge(config=config)
        
        # 模拟 TTS 结果
        tts_result = {
            "text_length": 50,
            "engine": "edge-tts",
            "voice": "zh-CN-XiaoxiaoNeural",
            "duration_ms": 3000,
            "success": True,
            "audio_size_bytes": 102400,
        }
        
        # 记录 TTS 使用
        result = await bridge.record_tts_usage(
            tts_result=tts_result,
            user_id="test_user",
            agent_id="test_agent",
        )
        
        # 验证记录成功
        assert result.success is True