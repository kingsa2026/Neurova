# -*- coding: utf-8 -*-
"""console 聊天链路的 AgentRun 台账接线（Yuxi 对比 P0-1/P0-2）。

契约（docs/Neurova_Yuxi代码级对比_2026-09-13.md 启发点 #1/#2/#8）：
- POST /console/chat 流式轮：请求先落库（intake queued）→ FIFO 晋升 running →
  流结束写终态（completed / failed / cancelled(user_stopped)）
- 同 session 已有活跃 run：新请求 SSE 先收 queued 事件，等待队头让位后正常流式
- /chat/stop：先落持久取消意图（cancel_requested），再走 task_tracker 真取消
- fail-open：台账任何异常不得阻断聊天
- NEUROVA_RUN_GATE=off：完全旁路（应急开关）
"""
from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from neurova.api.app import create_app
from neurova.core import agent_run_store as ars


class _StubAgent:
    """最小 Agent 替身：chat 经 event_emitter 发一个 chunk 后返回文本。"""

    def __init__(self, delay: float = 0.0, error: bool = False):
        self.delay = delay
        self.error = error

    async def chat(self, message, stream=True, session_id=None, metadata=None, model=None):
        emit = (metadata or {}).get("event_emitter")
        if self.delay:
            await __import__("asyncio").sleep(self.delay)
        if self.error:
            raise RuntimeError("stub llm down")
        if emit:
            emit("content", "hello-ledger")
        return {"text": "hello-ledger", "reasoning": None, "tool_messages": []}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_RUN_STORE_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setenv("NEUROVA_RUN_GATE", "on")
    ars.reset_agent_run_store()
    s = ars.AgentRunStore(tmp_path / "ledger.db")
    # 让全局 get_* 返回同一路径实例（console 接线经工厂取用）
    monkeypatch.setattr(ars, "_store", s)
    yield s
    ars.reset_agent_run_store()


@pytest.fixture()
def client(store, monkeypatch):
    # 真实 get_agent_instance 会拉起完整 Agent——测试必须钉桩（chat 行为
    # 由 _StubAgent 定义；个别用例再覆盖为 error 桩）
    from neurova.api.deps import get_current_user
    from neurova.api.endpoints import console as console_mod

    monkeypatch.setattr(
        console_mod, "get_agent_instance", lambda agent_id=None: _StubAgent()
    )
    app = create_app(enable_memory=False, enable_channels=False)
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "ledger-tester",
        "username": "ledger-tester",
    }
    return TestClient(app)


def _sse_types(response_text: str):
    types = []
    for line in response_text.splitlines():
        if line.startswith("data: "):
            try:
                types.append(json.loads(line[6:]).get("type"))
            except json.JSONDecodeError:
                pass
    return types


def test_chat_stream_writes_completed_run(client, store):
    sid = "led-c1"
    r = client.post(
        "/api/v1/console/chat",
        json={"message": "ledger-probe", "session_id": sid, "stream": True},
    )
    assert r.status_code == 200
    assert "hello-ledger" in r.text
    runs = store.list_runs(sid)
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"
    assert runs[0]["message_digest"] == "ledger-probe"[:200]


def test_chat_error_writes_failed_run(client, store, monkeypatch):
    sid = "led-c2"
    from neurova.api.endpoints import console as console_mod

    monkeypatch.setattr(
        console_mod,
        "get_agent_instance",
        lambda agent_id=None: _StubAgent(error=True),
        raising=False,
    )
    r = client.post(
        "/api/v1/console/chat",
        json={"message": "boom", "session_id": sid, "stream": True},
    )
    assert r.status_code == 200
    runs = store.list_runs(sid)
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"


def test_single_active_run_queues_then_proceeds(client, store):
    sid = "led-c3"
    # 预占：手工造一个活跃 run（模拟前一请求仍在流式中）
    blocker = store.intake(sid, "u", "a", "blocker")
    assert store.claim_next(sid, owner="blocker-w") == blocker

    def _release_later():
        time.sleep(0.5)
        store.finish(blocker, owner="blocker-w", status="completed")

    t = threading.Thread(target=_release_later)
    t.start()
    try:
        r = client.post(
            "/api/v1/console/chat",
            json={"message": "waited", "session_id": sid, "stream": True},
        )
    finally:
        t.join()
    assert r.status_code == 200
    types = _sse_types(r.text)
    assert "queued" in types, "被占用期间应先收到 queued 事件"
    assert types[-1] == "done"
    runs = {r_["message_digest"]: r_ for r_ in store.list_runs(sid)}
    assert runs["waited"]["status"] == "completed"


def test_stop_persists_cancel_intent(client, store):
    sid = "led-c4"
    r_run = store.intake(sid, "u", "a", "running")
    store.claim_next(sid, owner="w")
    resp = client.post(f"/api/v1/console/chat/stop?session_id={sid}")
    assert resp.status_code == 200
    assert store.cancel_requested(r_run) is True


def test_gate_off_bypasses_ledger(client, store, monkeypatch):
    monkeypatch.setenv("NEUROVA_RUN_GATE", "off")
    sid = "led-c5"
    r = client.post(
        "/api/v1/console/chat",
        json={"message": "no-ledger", "session_id": sid, "stream": True},
    )
    assert r.status_code == 200
    assert store.list_runs(sid) == []


def test_ledger_failure_never_breaks_chat(client, store, monkeypatch):
    """fail-open 验证：store 全坏（intake 抛错）聊天照常完成。"""
    sid = "led-c6"
    monkeypatch.setattr(ars.AgentRunStore, "intake", _boom, raising=True)
    r = client.post(
        "/api/v1/console/chat",
        json={"message": "resilient", "session_id": sid, "stream": True},
    )
    assert r.status_code == 200
    assert "done" in _sse_types(r.text)


def _boom(*a, **k):
    raise RuntimeError("ledger db on fire")


def test_startup_reconcile_converges_ghost_rows(tmp_path, monkeypatch):
    """启动收敛：上一进程遗留 running/queued 分别落 failed(process_died)/cancelled。"""
    db = tmp_path / "ghost.db"
    s1 = ars.AgentRunStore(db)
    g1 = s1.intake("sa", "u", "a", "1")
    s1.claim_next("sa", "w")
    s1.intake("sb", "u", "a", "2")
    s1.close()
    # 新实例（新进程）构造时自动 reconcile
    s2 = ars.AgentRunStore(db)
    assert s2.get(g1)["status"] == "failed"
    assert s2.get(g1)["error_type"] == "process_died"
    pending = [r for r in s2.list_runs("sb") if r["status"] == "cancelled"]
    assert pending and pending[0]["error_type"] == "server_restart"
    s2.close()
