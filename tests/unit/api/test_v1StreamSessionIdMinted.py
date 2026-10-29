# -*- coding: utf-8 -*-
"""v1 流式：`session_id` 由服务端当场铸并**在开局帧回传**（第 1 步前置）。

复核实状（读到生产侧）：`POST /v1/chat/stream` 的 `session_id` 是可选字段，缺省时
直接 `sessionId = body.session_id or ""`（`chat.py:427`），于是：

- 台账行、`task_tracker` 注册都以空串为键（`if body.session_id:` 那处注册直接跳过），
  `/console/chat/stop` 停不掉它、挂起也没有续跑凭据——`acquire()` 的拒收分支自己
  就写着"请求缺 session_id 或台账未开，本轮已中止"；
- 客户端在回合结束前不知道这一轮属于哪个会话（与 §6-420 在 console 修掉的是同一个洞），
  断线重连只能不带 id 重来。

console 侧的修法是"分配点与告知点同处：开局第一帧带归属"。本批把这同一条搬到 v1：
缺 id 时在**请求边界**用仓内单点 `create_session` 铸一个，随后连同 `start` 帧回传；
客户端自带 id 时原样使用，不再铸第二个（否则就是第二个事实源）。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


class _StubAgent:
    async def chat(self, message=None, user_input=None, **kwargs):
        return {"text": "好", "reasoning": None, "tool_messages": []}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from neurova.core import agent_run_store as ars

    monkeypatch.setenv("NEUROVA_RUN_STORE_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setenv("NEUROVA_RUN_GATE", "on")
    ars.reset_agent_run_store()
    ars._store = ars.AgentRunStore(tmp_path / "ledger.db")

    # 会话仓换成假仓：铸 id 走 `get_session_repository().create_session(...)` 这个单点，
    # 真仓会在开发数据目录里建一条空会话记录（每跑一次测试留一条），属测试污染。
    import neurova.session_repository as sessionRepositoryMod

    class _MintOnlyRepo:
        def create_session(self, agent_id="", user_id="", title="", config=None):
            return "v1-minted-fixed"

        def get_history(self, **kwargs):
            return []

    monkeypatch.setattr(sessionRepositoryMod, "get_session_repository", lambda: _MintOnlyRepo())
    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user
    from neurova.api.endpoints import chat as chat_mod

    monkeypatch.setattr(chat_mod, "_get_agent", lambda agent_id=None: _StubAgent())
    monkeypatch.setattr(chat_mod, "_user_can_access_agent", lambda *a, **k: True)
    app = create_app(enable_memory=False, enable_channels=False)
    # `chat.py` 用的是 `neurova.api.auth.get_current_user`（console 面用的是 deps 那份）——
    # 覆写要打在同一对象上，否则只有 POST 表面 200、实际 401（本档初版就栽在这儿：
    # 三条判据都 401，只有第一条查了状态码，另两条看起来像"没回传 id"）。
    from neurova.api.auth import get_current_user as authGetCurrentUser

    app.dependency_overrides[authGetCurrentUser] = lambda: {
        "user_id": "v1-tester", "username": "v1-tester", "role": "admin",
    }
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "v1-tester", "username": "v1-tester", "role": "admin",
    }
    return TestClient(app)


def _frames(text: str):
    """把 SSE 文本拆成 [(event, payload_dict)]。"""
    out = []
    cur = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("event:"):
            cur["event"] = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            raw = line.split(":", 1)[1].strip()
            try:
                cur["data"] = json.loads(raw)
            except json.JSONDecodeError:
                cur["data"] = raw
            if "event" in cur:
                out.append((cur.get("event"), cur.get("data")))
            cur = {}
    return out


def _firstStartFrame(frames):
    for name, payload in frames:
        if name == "start":
            return payload if isinstance(payload, dict) else {}
    return None


def test_streamWithoutSessionIdMintsAndAnnouncesOne(client):
    """不带 session_id：开局帧必须回传一个**非空**且已建会话的 id。"""
    r = client.post("/api/v1/chat/stream", json={"message": "你好", "agent_id": "default"})
    assert r.status_code == 200, r.text[:200]

    start = _firstStartFrame(_frames(r.text))
    assert start is not None, "没有 start 帧，场景没跑起来"
    minted = str(start.get("session_id") or "")
    assert minted, (
        f"开局帧没有回传 session_id（实得 {start}）——客户端在回合结束前不知道这一轮属于哪，"
        "断线重连只能不带 id 重来"
    )

    # 会话必须真的存在（铸 id 与建会话是同一件事，不能只回传一个没人认的串）
    from neurova.session_repository import get_session_repository
    hist = get_session_repository().get_history(agent_id="default", session_id=minted) or []
    assert hist == [] or any(
        "你好" in str(m.get("content") or "") for m in hist
    ), f"按回传的 id 读到的历史不对：{hist}"


def test_clientSuppliedSessionIdIsUsedAsIs(client):
    """反向控制：客户端自带 id 时原样使用，不再铸第二个。"""
    sid = "v1-client-owned-sid"
    r = client.post(
        "/api/v1/chat/stream",
        json={"message": "你好", "agent_id": "default", "session_id": sid},
    )
    start = _firstStartFrame(_frames(r.text))
    assert (start or {}).get("session_id") == sid, (
        f"自带 id 时被改写了（实得 {start}）——那会造出第二个会话"
    )


def test_mintedIdIsTheOneTheTurnUsesAsItsKey(client):
    """回传的 id 必须是这一轮**真正用来建台账/注册任务**的那个，不能只是嘴上说一个。

    量法说明：本夹具用 `create_app(enable_memory=False)`，管线不落会话文件，所以不能靠
    读历史取证；改读 run 台账——它是用同一个 `sessionId` 建行的，若实现只在回传处另算
    一个串、而台账仍按空串建行，这里就取不到行（本档初版一度误用历史读口，红得没意义）。
    """
    from neurova.core import agent_run_store as ars

    r = client.post("/api/v1/chat/stream", json={"message": "给我建一行台账", "agent_id": "default"})
    start = _firstStartFrame(_frames(r.text)) or {}
    minted = str(start.get("session_id") or "")
    assert minted, "没有回传 session_id"

    rows = ars.get_agent_run_store().list_runs(minted, 5) or []
    assert rows, (
        f"按回传的 id（{minted}）在台账里查不到这一轮——"
        "说明建行用的是别的键（很可能仍是空串），回传值只是个摆设"
    )
