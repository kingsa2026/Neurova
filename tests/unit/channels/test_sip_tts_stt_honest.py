# -*- coding: utf-8 -*-
"""任务2（资源型修复登记台账 2026-09-11 渠道域收尾）：SIP TTS/STT 模拟数据诚实化。

缺陷：requests 缺失分支 text_to_speech 返回 b""、speech_to_text 返回
"用户语音内容" 模拟数据——与 B-3/B-9 的诚实语义相悖（不虚构能力）。

契约：requests 缺失时 logger.warning("SIP 通道未实现...") 并返回 None；
防回归断言返回 None 且模拟数据字样不得回流（源级锁存）。
"""

import inspect
import logging

import pytest

import neurova.channels.sip as sip_module
from neurova.channels.sip import SIPAdapter


@pytest.fixture
def adapter():
    a = SIPAdapter()
    a.dashscope_api_key = "sk-unit-test"
    return a


def test_tts_without_requests_honest_failure(adapter, monkeypatch, caplog):
    """requests 缺失：TTS 诚实失败返回 None（原 [TTS模拟] return b"" 已清除）"""
    monkeypatch.setattr(sip_module, "REQUESTS_AVAILABLE", False)
    with caplog.at_level(logging.WARNING):
        out = adapter.text_to_speech("你好世界")

    assert out is None, "requests 缺失必须诚实失败，禁止返回模拟音频数据"
    assert "SIP 通道未实现" in caplog.text
    assert "TTS模拟" not in caplog.text


def test_stt_without_requests_honest_failure(adapter, monkeypatch, caplog):
    """requests 缺失：STT 诚实失败返回 None（原 [STT模拟] '用户语音内容' 已清除）"""
    monkeypatch.setattr(sip_module, "REQUESTS_AVAILABLE", False)
    with caplog.at_level(logging.WARNING):
        out = adapter.speech_to_text(b"\x00" * 32)

    assert out is None, "requests 缺失必须诚实失败，禁止返回模拟识别文本"
    assert "SIP 通道未实现" in caplog.text
    assert "STT模拟" not in caplog.text
    assert "用户语音内容" not in caplog.text


def test_sip_source_no_mock_data_residual():
    """源级锁存：text_to_speech/speech_to_text 不得再含模拟数据路径"""
    for fn in (SIPAdapter.text_to_speech, SIPAdapter.speech_to_text):
        src = inspect.getsource(fn)
        assert "模拟" not in src, f"{fn.__name__} 不得再出现模拟路径"
        assert 'return b""' not in src, f"{fn.__name__} 不得再返回空音频模拟数据"
        assert "用户语音内容" not in src, f"{fn.__name__} 不得再返回模拟识别文本"
