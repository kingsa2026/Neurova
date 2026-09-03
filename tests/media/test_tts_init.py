#!/usr/bin/env python3
"""测试TTS初始化"""

import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_tts():
    """测试TTS初始化"""
    try:
        from neurova.tts.manager import TTSManager, TTSConfig
        
        # 创建配置
        config = TTSConfig(
            engine="auto",  # 使用自动模式
            voice="zh-CN-XiaoxiaoNeural",
        )
        
        # 创建管理器
        manager = TTSManager(config=config)
        
        # 初始化
        print("开始初始化TTS管理器...")
        success = await manager.initialize()
        
        if success:
            print(f"TTS初始化成功，引擎: {manager.engine_name}")
            print(f"引擎状态: {manager.stats}")
            
            # 测试合成
            print("\n测试语音合成...")
            audio_data = await manager.synthesize("你好，这是测试语音。")
            if audio_data:
                print(f"合成成功，音频大小: {len(audio_data)} 字节")
            else:
                print("合成失败，返回空数据")
        else:
            print("TTS初始化失败")
            print(f"可用引擎状态: {manager.stats}")
            
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_tts())