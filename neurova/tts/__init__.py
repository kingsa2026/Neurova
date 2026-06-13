"""
TTS Module - 语音合成模块

支持多种 TTS 引擎（auto 模式自动 fallback）：
1. MOSS-TTS-Nano: 本地推理，支持声音克隆（优先）
2. Edge TTS: 在线，中文效果好（fallback）
3. MockTTS: 模拟，用于测试
"""


try:
    pass
except ImportError:
    pass

from neurova.tts.base import TTSBase
from neurova.tts.edge_tts import EdgeTTS
from neurova.tts.manager import TTSConfig, TTSManager
from neurova.tts.mock_tts_simple import MockTTSSimple
from neurova.tts.model_downloader import ModelDownloader, get_model_downloader

try:
    from neurova.tts.moss_nano import MOSSNanTTS
except ImportError:
    MOSSNanTTS = None

__all__ = [
    "TTSBase",
    "EdgeTTS",
    "MOSSNanTTS",
    "ModelDownloader",
    "get_model_downloader",
    "MockTTSSimple",
    "TTSManager",
    "TTSConfig",
]
