"""简单的语音系统集成测试"""
import sys
sys.path.insert(0, 'e:/项目/Neurova')

async def main():
    """测试语音系统集成"""
    try:
        from neurova.voice_engine import VoiceEngine, VoiceEngineType
        print("VoiceEngine 导入成功")
        
        from neurova.voice_memory_bridge import VoiceMemoryBridge
        print("VoiceMemoryBridge 导入成功")
        
        from neurova.tts.manager import TTSManager
        print("TTSManager 导入成功")
        
        from neurova.asr.manager import ASRManager
        print("ASRManager 导入成功")
        
        from neurova.channels.voice import VoiceAdapter
        print("VoiceAdapter 导入成功")
        
        # 测试 VoiceMemoryBridge
        bridge = VoiceMemoryBridge()
        print("VoiceMemoryBridge 实例创建成功")
        
        # 测试 ASR 记录
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
        print(f"ASR 记录结果: {result.success}")
        
        # 测试 TTS 记录
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
        print(f"TTS 记录结果: {tts_result.success}")
        
        print("所有集成测试通过！")
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())