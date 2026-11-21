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


def assertCausalFrameOrder(records):
    """因果序断言：只钉「有真因果」的帧对，不断言无因果帧之间的全局全序。

    真因果（必须成立，违者即红）：
    - 每个请求 out 必须先于它的应答 in（按 id 配对、seq 判定；
      _sendFrame 先记 out 再 flush，读泵最早在 flush 后才可能见到应答）；
    - observed/exited 必须最后（terminate 收口后才落账本）；
    - 同方向保持 FIFO：out 之间、in 之间各按 seq 递增；in 方向内部顺序确定
      （桩 agent 先写 initialize 应答再推 session/update，ping 应答须待
      收到 ping 才写，管道 FIFO + 单线程读泵保序）。

    无因果（合法交错，不得钉序）：session/update 是 agent 主动推送的通知，
    ping 是客户端随后发起的新请求——二者分属独立方向、互不依赖，其相对
    顺序取决于读泵线程与主线程的调度，两种交错都合法。旧断言把二者钉成
    全局全序（["out","in","in","out",...]），因此间歇性误报；本断言不弱化
    到恒真：帧数量、方向多重集、各帧内容、因果对、FIFO、observed 收尾
    全部逐项保留。
    """
    assert len(records) == 6, f"应恰好 6 帧（2 out / 3 in / 1 observed），实际 {len(records)}: {records}"
    directions = sorted(r["direction"] for r in records)
    assert directions == ["in", "in", "in", "observed", "out", "out"], (
        f"方向多重集不符：{[r['direction'] for r in records]}"
    )
    seqs = [r["seq"] for r in records]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), f"seq 须按文件序单调递增且唯一：{seqs}"

    outs = [r for r in records if r["direction"] == "out"]
    ins = [r for r in records if r["direction"] == "in"]
    observedRecs = [r for r in records if r["direction"] == "observed"]

    # 同方向 FIFO（文件序即 seq 序；readFrames 按文件序返回）
    assert [r["seq"] for r in outs] == sorted(r["seq"] for r in outs), "out 方向须保持 FIFO"
    assert [r["seq"] for r in ins] == sorted(r["seq"] for r in ins), "in 方向须保持 FIFO"

    # 出站顺序：先 initialize 握手，后 ping（发送方单线程顺序，真因果链的起点）
    assert outs[0]["frame"].get("method") == "initialize", f"第 1 个 out 应为 initialize：{outs[0]['frame']}"
    assert outs[1]["frame"].get("method") == "ping", f"第 2 个 out 应为 ping：{outs[1]['frame']}"
    initReq, pingReq = outs

    # 入站顺序（读泵 FIFO，桩时序确定）：initialize 应答 → session/update 通知 → ping 应答
    assert ins[0]["frame"].get("id") is not None, f"initialize 应答须带 id：{ins[0]['frame']}"
    assert ins[0]["frame"].get("id") == initReq["frame"].get("id"), "initialize 应答 id 须与请求配对"
    assert ins[1]["frame"].get("method") == "session/update", f"第 2 个 in 应为通知：{ins[1]['frame']}"
    assert ins[2]["frame"].get("id") == pingReq["frame"].get("id"), "ping 应答 id 须与请求配对"
    assert (ins[2]["frame"].get("result") or {}).get("pong") is True, f"ping 应答须 pong=true：{ins[2]['frame']}"

    # 因果对（跨方向真序，seq 判定）：请求 out 严格先于它的应答 in
    assert initReq["seq"] < ins[0]["seq"], "因果违规：initialize 请求必须先于其应答"
    assert pingReq["seq"] < ins[2]["seq"], "因果违规：ping 请求必须先于其应答"

    # 退出观测必须收口在最后
    assert len(observedRecs) == 1, f"observed 应恰好 1 条：{observedRecs}"
    assert observedRecs[0]["seq"] == seqs[-1], "observed/exited 必须是最后一帧"
    observed = observedRecs[0]["frame"]
    assert observed.get("type") == "exited", f"observed 帧类型应为 exited：{observed}"
    assert isinstance(observed.get("exit_code"), int), f"exit_code 应为 int：{observed}"


def test_startHandshakeSucceedsAndReturnsCapabilities():
    client, _, _ = makeClient("ok")
    try:
        result = client.start()
        assert result["protocolVersion"] == "1"
        # ACP 规范字段是 agentCapabilities（真机 CLIs 回包即此；G2 录制实证）
        assert "tools" in result["agentCapabilities"]
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
        # 因果序断言（见 assertCausalFrameOrder）：session/update 通知与 ping
        # 请求之间无因果关系，读泵/主线程调度使其两种交错都合法；请求→应答、
        # observed 收尾、同方向 FIFO 等真序逐项钉死。
        assertCausalFrameOrder(records)

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
