"""
TTS Module - 语音合成模块

支持多种TTS引擎：
1. Edge TTS（默认，在线，中文音色好，无需下载模型）
2. MOSS-TTS-Nano（可选，本地，支持中文，自动下载模型）
3. MockTTS（简单模拟，用于测试）
"""

# tts imports
import neurova.tts.base
import neurova.tts.edge_tts
import neurova.tts.manager
import neurova.tts.moss_nano
import neurova.tts.mock_tts_simple

# 导出主要类
from neurova.tts.base import TTSBase
from neurova.tts.edge_tts import EdgeTTS
from neurova.tts.moss_nano import MOSSNanTTS
from neurova.tts.mock_tts_simple import MockTTSSimple
from neurova.tts.manager import TTSManager, TTSConfig

__all__ = [
    "TTSBase",
    "EdgeTTS",
    "MOSSNanTTS",
    "MockTTSSimple",
    "TTSManager",
    "TTSConfig",
]