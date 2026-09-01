# -*- coding: utf-8 -*-
"""ASR 模型下载器与 whisper model_dir 修复测试（补课 4.2）。"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_registry_contains_whisper_entries():
    from neurova.asr.model_downloader import ASR_MODEL_REGISTRY, DEFAULT_ASR_MODEL

    assert DEFAULT_ASR_MODEL in ASR_MODEL_REGISTRY
    assert "whisper-base" in ASR_MODEL_REGISTRY
    assert ASR_MODEL_REGISTRY["whisper-base"]["model_file"] == "base.pt"


def test_is_model_ready_checks_file(tmp_path, monkeypatch):
    import neurova.asr.model_downloader as md

    monkeypatch.setattr(md, "get_asr_model_dir", lambda: tmp_path)
    assert md.is_model_ready("base") is False
    (tmp_path / "base.pt").write_bytes(b"x")
    assert md.is_model_ready("base") is True


def test_ensure_model_passes_download_root(tmp_path, monkeypatch):
    import neurova.asr.model_downloader as md

    captured = {}

    class FakeWhisper:
        @staticmethod
        def load_model(size, device=None, download_root=None):
            captured["size"] = size
            captured["device"] = device
            captured["download_root"] = download_root
            return MagicMock()

    monkeypatch.setitem(__import__("sys").modules, "whisper", FakeWhisper)
    model = md.ensure_model("base", device="cpu")
    assert model is not None
    assert captured["size"] == "base"
    assert captured["download_root"] == str(md.get_asr_model_dir())


def test_whisper_engine_uses_model_dir_as_download_root(tmp_path, monkeypatch):
    """锁定 model_dir 被忽略 bug 的修复：load_model 收到 download_root。"""
    import asyncio

    from neurova.asr.whisper_engine import WhisperEngine

    fake_whisper = MagicMock()
    fake_whisper.load_model.return_value = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "whisper", fake_whisper)
    monkeypatch.setitem(__import__("sys").modules, "torch", MagicMock())
    monkeypatch.setattr(
        "torch.cuda.is_available", lambda: False, raising=False
    )

    eng = WhisperEngine.__new__(WhisperEngine)
    from unittest.mock import MagicMock as _M

    eng._logger = _M()
    eng._model_dir = str(tmp_path / "whisper")
    eng._model_name = "base"
    eng._device = "cpu"
    eng._model = None
    eng._auto_download = True
    eng._total_requests = 0
    eng._total_inference_ms = 0.0
    eng._lock = __import__("threading").Lock()

    ok = asyncio.run(eng.initialize())
    assert ok is True
    call_kwargs = fake_whisper.load_model.call_args.kwargs
    assert call_kwargs.get("download_root") == str(tmp_path / "whisper")
