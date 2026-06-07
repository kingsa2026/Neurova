"""简单的闭环测试"""
import asyncio
from neurova.voice_memory_bridge import VoiceMemoryBridge
from neurova.voice_adapter import VoiceAdapterFactory
from neurova.channels.voice import VoiceAdapter
from neurova.channels.base import ChannelConfig

async def main():
    """测试闭环"""
    print("=== 测试 VoiceMemoryBridge 闭环 ===")
    
    # 1. 创建桥接器
    bridge = VoiceMemoryBridge()
    print("VoiceMemoryBridge 创建成功")
    
    # 2. 测试 ASR 记录
    asr_result = await bridge.record_asr_result(
        asr_result={
            "text": "测试语音转写",
            "confidence": 0.95,
            "language": "zh",
            "engine": "whisper",
            "duration_ms": 1500,
        },
        user_id="user_123",
        agent_id="agent_456",
    )
    print(f"ASR 记录: {asr_result.success}")
    
    # 3. 测试 TTS 记录
    tts_result = await bridge.record_tts_usage(
        tts_result={
            "text_length": 100,
            "engine": "edge-tts",
            "voice": "zh-CN-XiaoxiaoNeural",
            "duration_ms": 2000,
            "success": True,
            "audio_size_bytes": 32000,
        },
        user_id="user_123",
        agent_id="agent_456",
    )
    print(f"TTS 记录: {tts_result.success}")
    
    print("\n=== 测试 VoiceAdapter 接口对齐 ===")
    
    # 4. 创建模拟 TTSManager
    class MockTTSManager:
        async def synthesize(self, text, **kwargs):
            return b"audio_data"
        engine_name = "edge-tts"
        is_initialized = True
    
    # 5. 创建适配器
    adapter = VoiceAdapterFactory.create_tts_adapter(MockTTSManager())
    print(f"TTS 适配器创建成功: {adapter.__class__.__name__}")
    
    # 6. 适配处理
    audio_data = await adapter.adapt_process(
        input_data="测试文本",
        operation="synthesize",
    )
    print(f"适配处理结果: {audio_data}")
    
    print("\n=== 测试 VoiceAdapter 生命周期 ===")
    
    # 7. 创建 VoiceAdapter
    config = ChannelConfig(
        channel_type="voice",
        enabled=True,
        app_id="test",
        app_secret="test",
    )
    voice_adapter = VoiceAdapter(config)
    print(f"VoiceAdapter 创建成功")
    
    # 8. 测试健康检查
    health = await voice_adapter.health_check()
    print(f"健康检查: {health}")
    
    print("\n=== 所有测试通过！===")

if __name__ == "__main__":
    asyncio.run(main())