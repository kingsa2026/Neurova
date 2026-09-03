#!/usr/bin/env python3
"""直接测试EdgeTTS"""

import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_edge_tts():
    """直接测试EdgeTTS"""
    try:
        # 尝试导入edge_tts
        print("尝试导入edge_tts...")
        import edge_tts
        print(f"edge_tts导入成功，版本: {edge_tts.__version__}")
        
        # 测试合成
        print("\n测试语音合成...")
        communicate = edge_tts.Communicate(
            text="你好，这是EdgeTTS测试。",
            voice="zh-CN-XiaoxiaoNeural",
        )
        
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        
        print(f"合成成功，音频大小: {len(audio_data)} 字节")
        
        # 保存音频文件
        output_path = "edge_tts_test.mp3"
        with open(output_path, "wb") as f:
            f.write(audio_data)
        print(f"音频已保存到: {output_path}")
        
    except ImportError as e:
        print(f"导入失败: {e}")
        print("edge_tts未安装或依赖缺失")
        
        # 检查aiohttp
        try:
            import aiohttp
            print(f"aiohttp版本: {aiohttp.__version__}")
        except ImportError:
            print("aiohttp未安装")
            
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_edge_tts())