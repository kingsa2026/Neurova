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
    client = NeuacpClient(["definitely-missing-binary-xyz", "--flag"])
    with pytest.raises(Exception):
        client.start()
    assert not client.is_alive


# ---------- F2 帧留痕钩子（设计文档 §3.2） ----------

class TestFrameHooks:
    """setFrameKey 绑定后，出站/入站/退出观测按序落 frames 账本；未绑定不落盘。"""

    def test_frameHookRecordsOutAndInFramesInOrder(self):
        from neurova.agent.neuacp.frame_log import readFrames

        client, events, _ = makeClient("push_notify")
        client.setFrameKey("frames_client_1")
        client.start()
        try:
            client.request("ping", {"k": "v"})
            deadline = time.time() + 5
            while time.time() < deadline and not events:
                time.sleep(0.05)
            assert events, "未在超时内收到通知（测试前置失败）"
        finally:
            client.terminate()
        records = readFrames("frames_client_1")
        directions = [r["direction"] for r in records]
        # 桩时序：握手应答后立即推送 session/update，随后才是 ping 往返。
        assert directions == ["out", "in", "in", "out", "in", "observed"], (
            f"帧序不符：{directions}"
        )
        assert records[0]["frame"]["method"] == "initialize"
        assert records[1]["frame"].get("id") is not None
        # 入站通知在 _dispatch 之前留痕
        assert records[2]["frame"]["method"] == "session/update"
        assert records[3]["frame"]["method"] == "ping"
        assert records[4]["frame"].get("result", {}).get("pong") is True
        # 退出观测：terminate 收口后 observed/exited，退出码能拿到就带
        observed = records[5]["frame"]
        assert observed["type"] == "exited"
        assert isinstance(observed.get("exit_code"), int)
        seqs = [r["seq"] for r in records]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

    def test_noFrameKeyMeansNoFrameLog(self):
        from pathlib import Path

        from neurova.core.data_root import dataPath

        runs_dir = Path(dataPath("swarm_runs"))
        before = {p.name for p in runs_dir.glob("*.frames.jsonl")} if runs_dir.exists() else set()
        client, _, _ = makeClient("ok")
        client.start()
        try:
            client.request("ping", {})
        finally:
            client.terminate()
        after = {p.name for p in runs_dir.glob("*.frames.jsonl")} if runs_dir.exists() else set()
        assert after == before, "未设 frame_key（无主会话）不得新增任何帧账本文件"

    def test_observedExitFrameRecordsExitCodeOnCrash(self):
        from neurova.agent.neuacp.frame_log import readFrames

        client, _, crashes = makeClient("crash_after_init")
        client.setFrameKey("frames_client_3")
        client.start()
        deadline = time.time() + 5
        while time.time() < deadline and not crashes:
            time.sleep(0.05)
        assert crashes, "agent 退出后未触发 on_crash（测试前置失败）"
        records = []
        deadline = time.time() + 5
        while time.time() < deadline:
            records = readFrames("frames_client_3")
            if records and records[-1]["direction"] == "observed":
                break
            time.sleep(0.05)
        assert records, "崩溃路径也应有帧留痕"
        observed = records[-1]
        assert observed["direction"] == "observed"
        assert observed["frame"]["type"] == "exited"
        assert observed["frame"].get("exit_code") == 3, "EOF 崩溃路径应带上真实退出码"

    def test_setFrameKeyRoundTrip(self):
        client, _, _ = makeClient("ok")
        assert client._frame_key is None, "默认未绑定"
        client.setFrameKey("frames_client_4")
        assert client._frame_key == "frames_client_4"
        client.setFrameKey("")
        assert client._frame_key is None, "空串视为未绑定"
        client.setFrameKey(None)
        assert client._frame_key is None
