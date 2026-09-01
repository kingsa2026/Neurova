# -*- coding: utf-8 -*-
"""ASR 诚实降级防回归（补课 4.1）。

原状：funasr/whisper 未安装时 initialize() 假成功（_initialized=True），
funasr._transcribe_sync 返回"模拟FunASR识别结果"假文本——/transcribe
兜底会落到 mock 返回假识别污染上层。锁定诚实语义：
- 未安装引擎 initialize 返回 False
- FunASR 集成路径不产出假文本
- 生产默认链不含 mock；NEUROVA_ENV=test 时追加
"""
import pytest

from neurova.asr.manager import ASRManager, ASRConfig, FALLBACK_CHAIN


def _reset_singleton():
    import neurova.asr.manager as m

    if hasattr(m, "_asr_manager_instance"):
        m._asr_manager_instance = None


def test_funasr_uninstalled_returns_false(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "funasr":
            raise ImportError("No module named 'funasr'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    import asyncio

    from neurova.asr.funasr_engine import FunASREngine

    eng = FunASREngine.__new__(FunASREngine)
    eng._initialized = False
    from unittest.mock import MagicMock

    eng._logger = MagicMock()
    eng._model_dir = "models/asr/funasr"
    eng._model_name = "funasr"
    eng._device = "cpu"
    eng._model = None
    eng._lock = __import__("threading").Lock()
    ok = asyncio.run(eng.initialize())
    assert ok is False
    assert eng._initialized is False


def test_whisper_uninstalled_returns_false(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "whisper":
            raise ImportError("No module named 'whisper'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    import asyncio

    from neurova.asr.whisper_engine import WhisperEngine

    eng = WhisperEngine.__new__(WhisperEngine)
    eng._initialized = False
    from unittest.mock import MagicMock

    eng._logger = MagicMock()
    eng._model_dir = "models/asr/whisper"
    eng._model_name = "base"
    eng._device = "cpu"
    eng._model = None
    eng._lock = __import__("threading").Lock()
    ok = asyncio.run(eng.initialize())
    assert ok is False
    assert eng._initialized is False


def test_funasr_transcribe_never_returns_fake_text():
    from neurova.asr.funasr_engine import FunASREngine

    eng = FunASREngine.__new__(FunASREngine)
    eng._initialized = True  # 模拟外层标记
    eng._model = None  # 但模型未加载
    import asyncio

    result = asyncio.run(eng.transcribe(b"\x00" * 800, language="zh"))
    assert "模拟" not in (result.get("text") or "")
    assert result.get("error")  # 必须带错误说明而非静默假文本


def test_production_chain_excludes_mock():
    assert "mock" not in FALLBACK_CHAIN
    assert FALLBACK_CHAIN == ["funasr", "whisper"]
