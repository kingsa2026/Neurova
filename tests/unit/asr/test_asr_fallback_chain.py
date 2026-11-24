# -*- coding: utf-8 -*-
"""ASR fallback 链构造判据（2026-11-24）：测试态 mock 提到链首——单测起真 app
不再加载 funasr/torch 大模型（torch.load 在内存压力下原生段错误，api 回归
两次实崩）；生产链序不变；whisper 仍为管理员 opt-in。
"""
from __future__ import annotations

from neurova.asr.manager import ASRManager, FALLBACK_CHAIN


def test_test_env_puts_mock_first_and_skips_whisper():
    chain = ASRManager._build_fallback_chain(
        append_mock=True, mock_first=True, whisper_consent=False)
    assert chain[0] == "mock", "测试态 mock 必须在链首（否则单测加载 funasr/torch）"
    assert "whisper" not in chain, "未获同意的 whisper 不得参与"
    assert chain[1] == FALLBACK_CHAIN[0], "mock 之后仍按既有 fallback 链序"


def test_production_chain_unchanged_and_no_mock():
    chain = ASRManager._build_fallback_chain(
        append_mock=False, mock_first=False, whisper_consent=False)
    assert chain == ["funasr", "remote_whisper"], "生产链序不受测试态改造影响"
    assert "mock" not in chain


def test_mock_appended_at_tail_when_explicit():
    chain = ASRManager._build_fallback_chain(
        append_mock=True, mock_first=False, whisper_consent=False)
    assert chain[-1] == "mock"
    assert chain[0] == "funasr"


def test_whisper_participates_after_consent():
    chain = ASRManager._build_fallback_chain(
        append_mock=False, mock_first=False, whisper_consent=True)
    assert "whisper" in chain


def test_module_level_chain_never_mutated():
    before = list(FALLBACK_CHAIN)
    ASRManager._build_fallback_chain(append_mock=True, mock_first=True,
                                     whisper_consent=True)
    assert FALLBACK_CHAIN == before, "构造链不得改写模块级 FALLBACK_CHAIN"
