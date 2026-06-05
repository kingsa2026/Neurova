"""
TTS Module - 语音合成与音频理解模块

支持多种 TTS 引擎（auto 模式自动 fallback）：
1. MOSS-TTS-Nano: 本地推理，支持声音克隆（优先）
2. Edge TTS: 在线，中文效果好（fallback）
3. MockTTS: 模拟，用于测试

音频理解：
- MOSS-Audio: 本地语音识别 + 音频理解（需要 GPU）
"""

import neurova.tts.base
import neurova.tts.edge_tts
import neurova.tts.manager
import neurova.tts.moss_nano
import neurova.tts.moss_audio
import neurova.tts.model_downloader
import neurova.tts.mock_tts_simple

from neurova.tts.base import TTSBase
from neurova.tts.edge_tts import EdgeTTS
from neurova.tts.moss_nano import MOSSNanTTS
from neurova.tts.moss_audio import MOSSAudioEngine
from neurova.tts.model_downloader import ModelDownloader, get_model_downloader
from neurova.tts.mock_tts_simple import MockTTSSimple
from neurova.tts.manager import TTSManager, TTSConfig

__all__ = [
    "TTSBase",
    "EdgeTTS",
    "MOSSNanTTS",
    "MOSSAudioEngine",
    "ModelDownloader",
    "get_model_downloader",
    "MockTTSSimple",
    "TTSManager",
    "TTSConfig",
]
