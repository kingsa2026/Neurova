# -*- coding: utf-8 -*-
"""B-6（台账 2026-09-11 第五节）防回归：mobile WS 同连接流中途取消。

原缺陷：_handle_chat_send 在 WS receive 循环内被 await 整条流式回复，
同一连接后续的 chat:cancel 要等流结束才被处理（移动端"停止"无效）。

契约：
- chat:send spawn 独立 task（模块级引用集 + done_callback discard），
  receive 循环继续读消息；
- 流式中 chat:cancel → 在流 task 被取消 + 补发 chat:cancelled，循环继续可用；
- 流式中新 chat:send → error(chat_busy) 拒绝，不开第二条流；
- 流结束（done）后新 chat:send 正常放行；
- 连接断开 → 在流 task 收尸（引用集清空、生成器关闭）；
- 取消标记随流终态回收（资源修复 #3 语义不回退）。

隔离纪律：fake WS + monkeypatch _verify_ws_token/get_agent_instance，
无真实网络；脚本化 receive_text 用 Event 精确控制时序。
"""

import asyncio
import json
from typing import Any, List

import pytest
from fastapi import WebSocketDisconnect

from neurova.api.endpoints import mobile_pairing as mp


class _Wait:
    """脚本哨兵：receive_text 阻塞到 event 置位后再继续读脚本。"""

    def __init__(self, event: asyncio.Event):
        self.event = event


class FakeWS:
    """假 WebSocket：脚本化 receive_text，记录 send_json。"""

    def __init__(self, script: List[Any]):
        self.query_params = {"token": "tok"}
        self._script = list(script)
        self.sent: List[dict] = []

    async def accept(self):
        pass

    async def send_json(self, message):
        self.sent.append(message)

    async def receive_text(self):
        while True:
            if not self._script:
                raise WebSocketDisconnect(code=1000)
            item = self._script.pop(0)
            if isinstance(item, _Wait):
                await item.event.wait()
                continue
            if isinstance(item, Exception):
                raise item
            return item


class FakeStreamAgent:
    """chat_stream：每个 chunk 前 gate 放行（测试精确控制节奏），可观测关闭。"""

    def __init__(self, total: int = 5):
        self.total = total
        self.calls = 0
        self.gate = asyncio.Event()
        self.closed = True  # 尚未启动视作已关闭
        self.sent_count = 0

    async def chat_stream(self, **kwargs):
        self.calls += 1
        self.closed = False
        try:
            for i in range(self.total):
                await self.gate.wait()
                self.gate.clear()
                self.sent_count += 1
                yield f"c{i}"
        finally:
            self.closed = True


def _msg(**kwargs):
    kwargs.setdefault("type", "chat:send")
    return json.dumps(kwargs)


async def _eventually(pred, timeout: float = 3.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if pred():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("等待条件超时")


@pytest.fixture(autouse=True)
def _clean_mp_state():
    yield
    mp._ws_connections.clear()
    mp._cancelled_sessions.clear()
    mp._paired_devices.clear()
    mp._chat_tasks.clear()
    mp.MobileConnectionManager._instance = None


def _install_auth(monkeypatch):
    monkeypatch.setattr(
        mp, "_verify_ws_token", lambda token: {"user_id": "u1", "pairing_id": "p1"}
    )


def _install_agent(monkeypatch, agent):
    monkeypatch.setattr(
        "neurova.api.endpoints.get_agent_instance", lambda agent_id: agent
    )


class TestMidstreamCancel:
    @pytest.mark.asyncio
    async def test_midstream_cancel_stops_stream_and_loop_survives(self, monkeypatch):
        """流中途 cancel → 流被取消 + chat:cancelled 补发，循环继续可用。"""
        agent = FakeStreamAgent(total=5)
        _install_agent(monkeypatch, agent)
        _install_auth(monkeypatch)

        gate_loop = asyncio.Event()
        ws = FakeWS([
            _msg(type="chat:send", content="hi", session_id="s1", agent_id="default"),
            _Wait(gate_loop),
            _msg(type="chat:cancel", session_id="s1"),
            _msg(type="ping", ts=1),
        ])

        runner = asyncio.create_task(mp.mobile_websocket(ws))
        agent.gate.set()  # 放行第一个 chunk
        await _eventually(lambda: any(m.get("type") == "chat:chunk" for m in ws.sent))
        assert not agent.closed, "此刻流必须仍在进行中"

        gate_loop.set()  # 循环继续读 → cancel → ping
        await asyncio.wait_for(runner, timeout=5)
        await asyncio.sleep(0)  # 让 done_callback 跑完

        types = [m.get("type") for m in ws.sent]
        assert "chat:chunk" in types
        assert "chat:done" not in types, "取消后不得发送 chat:done"
        assert "chat:cancelled" in types, "取消必须补发 chat:cancelled 事件"
        assert "pong" in types, "取消后循环必须继续可用（ping→pong）"
        assert agent.calls == 1
        assert agent.closed, "在流生成器必须被关闭"
        assert agent.sent_count < agent.total, "流必须中途停止"
        assert not mp._chat_tasks, "结束的 task 必须从模块级引用集移除"
        assert "s1" not in mp._cancelled_sessions, "取消标记须随流终态回收（#3 语义）"

    @pytest.mark.asyncio
    async def test_cancel_unknown_session_keeps_marker_semantics(self, monkeypatch):
        """cancel 的 session 无在流 task 时保持 #3 孤儿标记语义（仅标记）。"""
        _install_auth(monkeypatch)
        gate_loop = asyncio.Event()
        ws = FakeWS([
            _msg(type="chat:cancel", session_id="orphan-sid"),
            _Wait(gate_loop),
        ])

        runner = asyncio.create_task(mp.mobile_websocket(ws))
        await _eventually(lambda: mp._cancelled_sessions.get("orphan-sid") is True)
        gate_loop.set()
        await asyncio.wait_for(runner, timeout=5)
        # 孤儿标记按 #3 语义保留（下次发送开始时消费/封顶逐出），连接结束不清


class TestDisconnectReaping:
    @pytest.mark.asyncio
    async def test_disconnect_reaps_inflight_stream_task(self, monkeypatch):
        """断开连接 → 在流 task 收尸（引用集清空、生成器关闭、无 done）。"""
        agent = FakeStreamAgent(total=5)
        _install_agent(monkeypatch, agent)
        _install_auth(monkeypatch)

        gate_loop = asyncio.Event()
        ws = FakeWS([
            _msg(type="chat:send", content="hi", session_id="s2", agent_id="default"),
            _Wait(gate_loop),  # 置位后脚本耗尽 → WebSocketDisconnect
        ])

        runner = asyncio.create_task(mp.mobile_websocket(ws))
        agent.gate.set()
        await _eventually(lambda: any(m.get("type") == "chat:chunk" for m in ws.sent))

        gate_loop.set()
        await asyncio.wait_for(runner, timeout=5)
        await asyncio.sleep(0)

        assert "chat:done" not in [m.get("type") for m in ws.sent]
        assert agent.closed, "断开连接后在流 task 必须被收尸（生成器关闭）"
        assert not mp._chat_tasks, "断开连接后 task 引用集必须清空"


class TestConcurrentSendRejected:
    @pytest.mark.asyncio
    async def test_send_while_streaming_rejected_with_busy_error(self, monkeypatch):
        """①同一连接流式中收到新 send → error(chat_busy) 拒绝，不开新流。"""
        agent = FakeStreamAgent(total=5)
        _install_agent(monkeypatch, agent)
        _install_auth(monkeypatch)

        ev1, ev2 = asyncio.Event(), asyncio.Event()
        ws = FakeWS([
            _msg(type="chat:send", content="hi", session_id="s3", agent_id="default"),
            _Wait(ev1),
            _msg(type="chat:send", content="again", session_id="s3", agent_id="default"),
            _Wait(ev2),
        ])

        runner = asyncio.create_task(mp.mobile_websocket(ws))
        agent.gate.set()
        await _eventually(lambda: any(m.get("type") == "chat:chunk" for m in ws.sent))

        ev1.set()  # 循环读到第二个 send
        await _eventually(
            lambda: any(
                m.get("type") == "error" and m.get("code") == "chat_busy" for m in ws.sent
            )
        )
        assert agent.calls == 1, "流式中新 send 必须被拒绝，不得开第二条流"

        ev2.set()
        await asyncio.wait_for(runner, timeout=5)
        await asyncio.sleep(0)
        assert agent.calls == 1
        assert not mp._chat_tasks

    @pytest.mark.asyncio
    async def test_new_send_allowed_after_stream_done(self, monkeypatch):
        """流结束（done）后新 send 正常放行——循环与在流状态可复用。"""
        agent = FakeStreamAgent(total=2)
        _install_agent(monkeypatch, agent)
        _install_auth(monkeypatch)

        ev1, ev2 = asyncio.Event(), asyncio.Event()
        ws = FakeWS([
            _msg(type="chat:send", content="q1", session_id="s4", agent_id="default"),
            _Wait(ev1),
            _msg(type="chat:send", content="q2", session_id="s4", agent_id="default"),
            _Wait(ev2),
        ])

        runner = asyncio.create_task(mp.mobile_websocket(ws))
        for i in range(2):  # 完成第一条流
            agent.gate.set()
            await _eventually(lambda: agent.sent_count >= i + 1)
        await _eventually(lambda: any(m.get("type") == "chat:done" for m in ws.sent))

        ev1.set()  # 第二个 send → 应开新流
        agent.gate.set()
        await _eventually(lambda: agent.sent_count >= 3)
        agent.gate.set()
        await _eventually(lambda: agent.sent_count >= 4)

        ev2.set()
        await asyncio.wait_for(runner, timeout=5)
        await asyncio.sleep(0)

        assert agent.calls == 2, "流结束后新 send 必须放行"
        assert [m["type"] for m in ws.sent].count("chat:done") == 2
        assert not mp._chat_tasks
