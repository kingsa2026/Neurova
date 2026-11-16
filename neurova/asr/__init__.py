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

# 条件导入 FunASR（funasr 依赖在引擎方法内惰性加载，模块本身可安全导入；
# 审计 §3.5-5：原形是 `try: pass; __all__.append("FunASREngine")`——名字进了
# __all__ 却从未导入，`from neurova.asr import FunASREngine` 必 ImportError）
try:
    from neurova.asr.funasr_engine import FunASREngine

    __all__.append("FunASREngine")
except ImportError as _e:
    # funasr_engine 依赖面不可用时保持 fail-soft，但不把不存在的名字留在 __all__
    import logging

    logging.getLogger(__name__).debug("FunASREngine 不可用（funasr 依赖未装?）: %s", _e)
