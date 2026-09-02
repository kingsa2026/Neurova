# -*- coding: utf-8 -*-
"""FunASR 真实现测试（补课 4.2 续：Paraformer 中文优先）。

锁定：AutoModel 加载链、generate 推理路径、加载失败诚实降级、
mock 仅测试态追加语义（与 whisper 共存的双引擎 fallback 链）。
"""
import asyncio
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def fake_funasr(monkeypatch):
    """注入 fake funasr 模块（AutoModel/接口形状对齐真包）。"""
    import sys
    import types

    fake = types.ModuleType("funasr")
    captured = {}

    class FakeAutoModel:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def generate(self, input=None, batch_size_s=None, **kw):
            captured["audio_len"] = len(input)
            return [{"text": "你好世界"}]

    fake.AutoModel = FakeAutoModel
    monkeypatch.setitem(sys.modules, "funasr", fake)
    return captured


def test_initialize_builds_automodel_with_paraformer(fake_funasr):
    from neurova.asr.funasr_engine import FunASREngine

    eng = FunASREngine(model_dir="models/asr/funasr", device="cpu")
    ok = asyncio.run(eng.initialize())
    assert ok is True
    assert eng._initialized is True
    # 中文优先：未显式指定 model id 时默认 paraformer-zh
    assert fake_funasr["kwargs"]["model"] == "paraformer-zh"
    assert fake_funasr["kwargs"]["device"] == "cpu"


def test_transcribe_real_generate_path(fake_funasr):
    from neurova.asr.funasr_engine import FunASREngine

    eng = FunASREngine(model_dir="models/asr/funasr", device="cpu")
    asyncio.run(eng.initialize())

    # 1 秒 16kHz 正弦静音（soundfile 可读的 wav bytes 由 _load_audio 消费）
    import io as _io
    import struct
    import wave

    buf = _io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"".join(struct.pack("<h", 0) for _ in range(16000)))

    result = asyncio.run(eng.transcribe(buf.getvalue(), language="zh"))
    assert result["text"] == "你好世界"
    assert result.get("error") is None
    assert result["duration_sec"] == pytest.approx(1.0, abs=0.1)


def test_load_failure_degrades_honestly(monkeypatch):
    import sys
    import types

    fake = types.ModuleType("funasr")

    class BoomAutoModel:
        def __init__(self, **kwargs):
            raise RuntimeError("model download failed")

    fake.AutoModel = BoomAutoModel
    monkeypatch.setitem(sys.modules, "funasr", fake)

    from neurova.asr.funasr_engine import FunASREngine

    eng = FunASREngine(model_dir="models/asr/funasr", device="cpu")
    ok = asyncio.run(eng.initialize())
    assert ok is False
    assert eng._initialized is False


def test_uninstalled_still_returns_false(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "funasr":
            raise ImportError("No module named 'funasr'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

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
