"""
ASR Module - 语音识别与音频理解模块

支持多种 ASR 引擎（auto 模式自动 fallback）：
1. FunASR: 本地语音识别（优先）
2. Whisper: 本地语音识别（fallback）
3. MockASR: 模拟，用于测试

音频理解：
- 基于 ASR + LLM 的音频理解
"""

from neurova.asr.base import ASRBase
from neurova.asr.manager import ASRConfig, ASRManager
from neurova.asr.mock_asr import MockASREngine
from neurova.asr.whisper_engine import WhisperEngine

__all__ = [
    "ASRBase",
    "ASRManager",
    "ASRConfig",
    "WhisperEngine",
    "MockASREngine",
]

# 条件导入 FunASR（可能需要额外依赖）
try:
    pass

    __all__.append("FunASREngine")
except ImportError:
    pass
