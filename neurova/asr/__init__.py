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
# FunASR 无条件导入（审计 §3.5-5：原形是 `__all__.append("FunASREngine")` 动态追加，
# 静态扫描不可见，名字成了"隐式公开面"。funasr/torch 等重依赖都在引擎方法内惰性
# 加载，funasr_engine 的模块级 import 全部安全，无条件导入不会失败）。
from neurova.asr.funasr_engine import FunASREngine

__all__ = [
    "ASRBase",
    "ASRManager",
    "ASRConfig",
    "WhisperEngine",
    "MockASREngine",
    "FunASREngine",
]
