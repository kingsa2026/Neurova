# -*- coding: utf-8 -*-
"""D-G 互操作根修：initialize 的 protocolVersion 线上类型必须是整数。

ACP 规范 ProtocolVersion = integer(uint16)；本仓客户端曾发字符串 "1"，
假 agent 不校验类型故从未暴露，真实 CLI（opencode/claude-code/codex 适配器）
一律 -32602 Invalid params。本测试用严格校验 agent（真 stdio）钉住线上类型。
"""
import sys
from pathlib import Path

import pytest

from neurova.agent.neuacp.acp_client import NeuacpClient

_STRICT_AGENT = Path(__file__).resolve().parent / "strict_initialize_agent.py"


def _make_client() -> NeuacpClient:
    return NeuacpClient(command=[sys.executable, str(_STRICT_AGENT)])


def test_initialize_sends_integer_protocol_version():
    """握手 initialize 的 protocolVersion 线上必须是整数；字符串被真 CLI 拒绝。"""
    client = _make_client()
    try:
        handshake = client.start()
        assert handshake is not None
        assert handshake.get("protocolVersion") == 1
    finally:
        client.terminate()


def test_initialize_accepts_custom_version_integer():
    client = NeuacpClient(command=[sys.executable, str(_STRICT_AGENT)])
    try:
        handshake = client.start(protocol_version="2")
        assert handshake.get("protocolVersion") == 2
    finally:
        client.terminate()
