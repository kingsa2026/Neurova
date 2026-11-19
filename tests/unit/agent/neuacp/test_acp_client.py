# -*- coding: utf-8 -*-
"""A1 红灯：NeuacpClient（ACP v1 JSON-RPC over stdio 客户端）契约测试。

覆盖：initialize 握手成功/版本协商 fail-closed、request 按 id 配对、
UTF-8 往返、通知回调、崩溃回调、超长帧 fail-closed、terminate。
"""
import sys
import time
from pathlib import Path

import pytest

from neurova.agent.neuacp.acp_client import (
    NeuacpClient,
    NeuacpProtocolError,
)

FAKE_AGENT = Path(__file__).with_name("fake_acp_agent.py")


def makeClient(mode, **kwargs):
    events = []
    crashes = []
    client = NeuacpClient(
        [sys.executable, str(FAKE_AGENT)],
        cwd=str(FAKE_AGENT.parent),
        env_extra={"FAKE_ACP_MODE": mode},
        on_event=lambda method, params: events.append((method, params)),
        on_crash=lambda reason: crashes.append(reason),
        **kwargs,
    )
    return client, events, crashes


def test_startHandshakeSucceedsAndReturnsCapabilities():
    client, _, _ = makeClient("ok")
    try:
        result = client.start()
        assert result["protocolVersion"] == "1"
        assert "tools" in result["serverCapabilities"]
        assert client.is_alive
    finally:
        client.terminate()


def test_startFailsClosedOnVersionMismatch():
    client, _, _ = makeClient("bad_version")
    with pytest.raises(NeuacpProtocolError):
        client.start()
    assert not client.is_alive


def test_startFailsClosedOnMissingVersion():
    client, _, _ = makeClient("no_version")
    with pytest.raises(NeuacpProtocolError):
        client.start()
    assert not client.is_alive


def test_requestPairsResponseByIdWithUtf8Roundtrip():
    client, _, _ = makeClient("ok")
    client.start()
    try:
        payload = {"task": "实现登录页", "tags": ["前端", "组件"]}
        result = client.request("ping", payload)
        assert result["pong"] is True
        assert result["echo"] == payload
    finally:
        client.terminate()


def test_onEventReceivesNotification():
    client, events, _ = makeClient("push_notify")
    client.start()
    try:
        deadline = time.time() + 5
        while time.time() < deadline and not events:
            time.sleep(0.05)
        assert events, "未在超时内收到 session/update 通知"
        method, params = events[0]
        assert method == "session/update"
        assert params["update"]["content"]["text"] == "你好 Neuacp"
    finally:
        client.terminate()


def test_agentCrashTriggersOnCrash():
    client, _, crashes = makeClient("crash_after_init")
    client.start()
    deadline = time.time() + 5
    while time.time() < deadline and not crashes:
        time.sleep(0.05)
    assert crashes, "agent 退出后未触发 on_crash"
    assert "3" in crashes[0] or "exit" in crashes[0].lower()
    assert not client.is_alive


def test_oversizedFrameFailsClosed():
    client, _, crashes = makeClient("oversize")
    client.start()
    deadline = time.time() + 5
    while time.time() < deadline and not crashes:
        time.sleep(0.05)
    assert crashes, "超长帧未触发 fail-closed"
    assert "frame" in crashes[0].lower()
    assert not client.is_alive


def test_terminateStopsProcess():
    client, _, _ = makeClient("ok")
    client.start()
    assert client.is_alive
    client.terminate()
    assert not client.is_alive


def test_startFailsGracefullyWhenBinaryMissing():
    client = NeuacpClient([sys.executable, "definitely_missing_binary_xyz.py"])
    with pytest.raises(Exception):
        client.start()
    assert not client.is_alive
