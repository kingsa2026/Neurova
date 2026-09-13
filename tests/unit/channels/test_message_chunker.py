# -*- coding: utf-8 -*-
"""渠道出站分片器测试（防截断统一层）。"""
from __future__ import annotations

from neurova.channels.message_chunker import split_message, text_limit_for


def test_short_text_single_chunk():
    assert split_message("你好", 4000) == ["你好"]


def test_no_content_loss_and_within_limit():
    text = "段落一。\n\n" + ("这是一段很长的中文句子。" * 400) + "\n\n结尾。"
    limit = 1000
    chunks = split_message(text, limit)
    assert all(len(c) <= limit for c in chunks), "存在超上限分片"
    # 不丢字符：各段拼接后应包含原文的所有非分隔内容
    joined = "".join(chunks)
    assert "段落一" in joined and "结尾" in joined
    assert joined.replace("\n\n", "").count("这是一段很长的中文句子。") == text.count("这是一段很长的中文句子。")


def test_hard_wrap_for_single_huge_word():
    text = "a" * 5000
    chunks = split_message(text, 1000)
    assert all(len(c) <= 1000 for c in chunks)
    assert "".join(chunks) == text


def test_empty_returns_single_empty():
    assert split_message("", 100) == [""]


def test_channel_limits_present():
    assert text_limit_for("telegram") <= 4096
    assert text_limit_for("wecom") < text_limit_for("telegram")
    assert text_limit_for("unknown_channel") > 0
