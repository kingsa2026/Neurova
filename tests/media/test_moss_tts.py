#!/usr/bin/env python3
"""测试MOSSNanTTS"""

import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_moss_tts():
    """测试MOSSNanTTS"""
    try:
        from neurova.tts.moss_nano import MOSSNanTTS
        
        print("创建MOSSNanTTS实例...")
        tts = MOSSNanTTS()
        
        print("初始化MOSSNanTTS...")
        success = await tts.initialize()
        
        if success:
            print("MOSSNanTTS初始化成功!")
            
            # 测试合成
            print("\n测试语音合成...")
            audio_data = await tts.synthesize("你好，这是MOSSNanTTS测试。")
            if audio_data:
                print(f"合成成功，音频大小: {len(audio_data)} 字节")
                
                # 保存音频文件
                output_path = "moss_tts_test.wav"
                with open(output_path, "wb") as f:
                    f.write(audio_data)
                print(f"音频已保存到: {output_path}")
            else:
                print("合成失败，返回空数据")
        else:
            print("MOSSNanTTS初始化失败")
            
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_moss_tts())