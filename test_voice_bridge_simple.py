"""简单的 VoiceMemoryBridge 测试"""
import asyncio
from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

async def main():
    """测试 VoiceMemoryBridge"""
    print("创建 VoiceMemoryBridge 实例...")
    bridge = VoiceMemoryBridge()
    
    print("测试 record_asr_result...")
    result = await bridge.record_asr_result(
        asr_result={
            "text": "测试文本",
            "confidence": 0.9,
            "language": "zh",
            "engine": "whisper",
            "duration_ms": 1000,
        },
        user_id="test_user",
        agent_id="test_agent",
    )
    print(f"ASR 结果: {result.success}")
    
    print("测试 record_tts_usage...")
    tts_result = await bridge.record_tts_usage(
        tts_result={
            "text_length": 100,
            "engine": "edge-tts",
            "voice": "zh-CN-XiaoxiaoNeural",
            "duration_ms": 2000,
            "success": True,
            "audio_size_bytes": 32000,
        },
        user_id="test_user",
        agent_id="test_agent",
    )
    print(f"TTS 结果: {tts_result.success}")
    
    print("测试完成！")

if __name__ == "__main__":
    asyncio.run(main())