# -*- coding: utf-8 -*-
"""P2-8 第二批：让位闸接进**真回合入口**，超限落 `parked` 并可人工续跑。

判据全部打在 HTTP 面上（真 `create_app` + `TestClient`），不在单元里直调闸——
§6-5 这条链断的正是"闸写好了但没人问"，而上一批的活体还量出过更硬的一格：
端点每次必 500（§6-44），只测 `checker.check_yield_rules()` 永远看不见它。

契约（拍板三条）：**回合入口一次**、**超时落库 parked 并立即收尾**、
**续跑权限＝会话属主 + 管理员**。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from neurova.api.app import create_app
from neurova.collaboration.glance_yield_rules import GlanceYieldChecker
from neurova.core import agent_run_store as ars

AGENT_ID = "gate-agent"
MODEL = "gpt-test"

OWNER = {"user_id": "owner-1", "username": "owner-1", "role": "user"}
ADMIN = {"user_id": "root-9", "username": "root-9", "role": "admin"}
STRANGER = {"user_id": "other-3", "username": "other-3", "role": "user"}


class _RecordingAgent:
    """记录"这一轮到底跑没跑"——挂起时它一次都不该被调用。"""

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    async def chat(self, message, stream=True, session_id=None, metadata=None, model=None):
        self.calls.append({"message": message, "user_id": (metadata or {}).get("user_id", "")})
        emit = (metadata or {}).get("event_emitter")
        if emit:
            emit("content", "hello-gate")
        return {"text": "hello-gate", "reasoning": None, "tool_messages": []}


def _sseEvents(text: str) -> List[Dict[str, Any]]:
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


def _types(text: str) -> List[str]:
    return [e.get("type") for e in _sseEvents(text)]


@pytest.fixture()
def runStore(tmp_path, monkeypatch):
    db = tmp_path / "gate.db"
    monkeypatch.setenv("NEUROVA_RUN_STORE_DB", str(db))
    monkeypatch.setenv("NEUROVA_RUN_GATE", "on")
    # 等待预算压到秒级以下：策略本身由 test_yieldGateWaitPolicy.py 钉，这里只验接线
    monkeypatch.setenv("NEUROVA_YIELD_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("NEUROVA_YIELD_WAIT_CAP_SECONDS", "0.05")
    ars.reset_agent_run_store()
    store = ars.AgentRunStore(db)
    monkeypatch.setattr(ars, "_store", store)
    yield store
    ars.reset_agent_run_store()


@pytest.fixture()
def yieldChecker(monkeypatch):
    """独占 checker 单例 + 可预期冷却（走生产触发口，不塞私有字典）。

    用 `monkeypatch` 换模块全局而不是 `await reset_glance_yield_checker()`：
    本文件的夹具是同步的，而那个重置入口是协程工厂——在同步夹具里裸调它
    正是 §6-5 那条病灶的形态（创建协程后丢弃、零异常零效果）。
    """
    monkeypatch.setattr(GlanceYieldChecker, "DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS", 3600.0)
    monkeypatch.setattr(
        "neurova.collaboration.glance_yield_rules._glance_checker_instance",
        GlanceYieldChecker(),
        raising=False,
    )
    from neurova.collaboration import glance_yield_rules as gyr

    return gyr._glance_checker_instance


_MISSING_OVERRIDE = object()


@pytest.fixture()
def makeClient(request, monkeypatch):
    """按身份造 client——**每次显式设定或清掉**身份覆盖。

    `create_app()` 返回进程内缓存的同一个 app（`neurova/api/app.py:1303`），
    `dependency_overrides` 于是是跨用例、跨文件共享的全局态。不清掉上一条留下的
    身份，"匿名请求"会带着别人的身份进来，判据就会红错方向（本文件第一版就这样）。
    """
    from neurova.api.deps import get_current_user
    from neurova.api.endpoints import console as console_mod

    def _make(agent: _RecordingAgent, identity: Optional[Dict[str, Any]]) -> TestClient:
        monkeypatch.setattr(console_mod, "get_agent_instance", lambda agent_id=None: agent)
        app = create_app(enable_memory=False, enable_channels=False)
        previous = app.dependency_overrides.get(get_current_user, _MISSING_OVERRIDE)
        if identity is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = lambda: dict(identity)

        def _restore() -> None:
            if previous is _MISSING_OVERRIDE:
                app.dependency_overrides.pop(get_current_user, None)
            else:
                app.dependency_overrides[get_current_user] = previous

        request.addfinalizer(_restore)
        return TestClient(app)

    return _make


def _postChat(makeClient, session_id: str, message: str) -> Any:
    agent = _RecordingAgent()
    client = makeClient(agent, OWNER)
    resp = client.post(
        "/api/v1/console/chat",
        json={
            "message": message,
            "session_id": session_id,
            "stream": True,
            "agent_id": AGENT_ID,
            "model": MODEL,
        },
    )
    return resp, agent


def _parkATurn(makeClient, runStore, yieldChecker, session_id: str):
    """走真端点把一条回合落到 parked，返回 (run_id, SSE 原文)。"""
    yieldChecker.trigger_rate_limit(AGENT_ID)
    resp, agent = _postChat(makeClient, session_id, "park-me")
    assert resp.status_code == 200
    assert "parked" in _types(resp.text), f"回合入口没把超限落成 parked 事件：{_types(resp.text)}"
    assert agent.calls == [], "挂起却仍然跑了这一轮"
    rows = runStore.list_runs(session_id)
    assert len(rows) == 1
    return rows[0]["run_id"], resp.text


def testTurnEntryConsultsYieldGateExactlyOnce(makeClient, runStore, yieldChecker, monkeypatch):
    """没让位时也要问一次——"接了但从不问"和"没接"在行为上无法区分，必须钉住。

    间谍打在 `core.agent_run_ledger` 的那一处闸口调用上（第三批起，四个入口共用
    同一份准入实现，闸口不再住在 console 里）——**行为主张没变**：网页回合入口
    恰好问一次、参数取真源。
    """
    import neurova.core.agent_run_ledger as ledgerMod
    from neurova.agent import turn_coordinator as gate_mod

    calls: List[Dict[str, Any]] = []
    realGate = gate_mod.requestYieldGate

    async def spy(**kwargs):
        calls.append(dict(kwargs))
        return await realGate(**kwargs)

    monkeypatch.setattr(ledgerMod, "requestYieldGate", spy)
    resp, agent = _postChat(makeClient, "g-once", "normal-turn")

    assert resp.status_code == 200
    assert len(agent.calls) == 1, "闸把正常回合也拦了"
    assert len(calls) == 1, f"回合入口应恰好问一次闸，实得 {len(calls)} 次"
    assert calls[0]["agentId"] == AGENT_ID and calls[0]["modelName"] == MODEL
    assert calls[0]["sessionId"] == "g-once" and calls[0]["userInput"] == "normal-turn"


def testOverBudgetParksWithoutRunningTheTurnAndClosesStream(makeClient, runStore, yieldChecker):
    """超限这一轮：落库 parked（带原因与载荷）、SSE parked+done 立即收尾、不创建执行任务。"""
    yieldChecker.trigger_rate_limit(AGENT_ID)
    resp, agent = _postChat(makeClient, "g-park", "park-me")

    types = _types(resp.text)
    assert "parked" in types and types[-1] == "done", f"须以 parked+done 收尾：{types}"
    assert "chunk" not in types, "挂起后不该有任何模型输出"
    assert agent.calls == []

    row = runStore.list_runs("g-park")[0]
    assert row["status"] == ars.PARKED_STATUS
    assert row["park_reason"] and row["park_reason"] != "model_pin_violation"
    assert "park-me" in (row["resume_payload"] or ""), "续跑要用的原文没落库"
    assert runStore.active_run("g-park") is None


def testWaitingRenewsLeaseEveryAttempt(makeClient, runStore, yieldChecker, monkeypatch):
    """等 2 次 × 上限 20s（总 200s）远超租约 90s：每次等待都必须续租，
    否则挂起判据会被 reconcile_stale 误杀成 failed，用户只看到"莫名失败"。"""
    renewals: List[str] = []
    realHeartbeat = ars.AgentRunStore.heartbeat

    def spyHeartbeat(self, run_id, owner):
        renewals.append(run_id)
        return realHeartbeat(self, run_id, owner)

    monkeypatch.setattr(ars.AgentRunStore, "heartbeat", spyHeartbeat)
    from neurova.core.agent_run_ledger import AgentRunLedger  # 第三批起台账住在 core（四入口共用）

    # 反证前提：节流窗口还在（否则本判据退化成"每轮都续"的平凡断言）
    assert AgentRunLedger.HEARTBEAT_SECONDS >= 5.0

    run_id, sseBody = _parkATurn(makeClient, runStore, yieldChecker, "g-lease")

    assert renewals.count(run_id) >= 2, (
        f"等待期只续租 {renewals.count(run_id)} 次（5s 节流把等待期全跳过了）"
    )


def testWaitingTellsTheClientOnTheExistingRetrySurface(makeClient, runStore, yieldChecker):
    """等待期得让用户看见在退避——复用既有 `retry` 事件，不新造第三种状态面。"""
    run_id, sseBody = _parkATurn(makeClient, runStore, yieldChecker, "g-progress")
    retries = [e for e in _sseEvents(sseBody) if e.get("type") == "retry"]
    assert retries, "等待期没有任何进度事件，用户只能对着转圈猜"
    assert all(e.get("source") == "glance_yield" for e in retries)
    assert runStore.get(run_id)["status"] == ars.PARKED_STATUS


def testOwnerResumesTheSameRunRow(makeClient, runStore, yieldChecker):
    """属主点续跑：复用原行跑完（库里仍只有 1 条），载荷在换手时即清空。"""
    run_id, sseBody = _parkATurn(makeClient, runStore, yieldChecker, "g-resume")
    yieldChecker._rate_limited_agents.pop(AGENT_ID, None)  # 冷却过了才可能真跑

    agent = _RecordingAgent()
    resp = makeClient(agent, OWNER).post(f"/api/v1/console/chat/resume?run_id={run_id}")

    assert resp.status_code == 200
    assert "hello-gate" in resp.text, "续跑没真的把这一轮跑完"
    rows = runStore.list_runs("g-resume")
    assert len(rows) == 1 and rows[0]["run_id"] == run_id, "续跑另起一行＝同一回合两个身份"
    assert rows[0]["status"] == "completed"
    assert rows[0]["resume_payload"] in (None, "")
    assert agent.calls[0]["message"] == "park-me", "续跑用的不是挂起时那条原文"


def testResumeRejectsStrangersAndAnonymous(makeClient, runStore, yieldChecker):
    """挂起的是别人的回合：陌生账号 403、匿名 401（这条端点不开例外）。"""
    run_id, sseBody = _parkATurn(makeClient, runStore, yieldChecker, "g-auth")

    denied = makeClient(_RecordingAgent(), STRANGER).post(
        f"/api/v1/console/chat/resume?run_id={run_id}"
    )
    assert denied.status_code == 403, f"非属主竟可续跑他人回合：{denied.status_code}"

    unauth = makeClient(_RecordingAgent(), None).post(
        f"/api/v1/console/chat/resume?run_id={run_id}"
    )
    assert unauth.status_code == 401, f"匿名续跑没被鉴权挡住：{unauth.status_code}"

    assert runStore.get(run_id)["status"] == ars.PARKED_STATUS, "被拒的续跑不得改动行状态"

    # 判序也要钉：终态行若先回 409，就等于向陌生账号确认"这条 run 存在且已结束"
    done = runStore.intake("g-auth", OWNER["user_id"], AGENT_ID, "already-done")
    assert runStore.claim_next("g-auth") == done
    assert runStore.finish(done, ars.OWNER_IDENTITY, "completed")
    terminal = makeClient(_RecordingAgent(), STRANGER).post(
        f"/api/v1/console/chat/resume?run_id={done}"
    )
    assert terminal.status_code == 403, (
        f"陌生账号先从终态行读到了状态：{terminal.status_code}（身份判定必须在状态判定之前）"
    )


def testAdminResumeExecutesAsTheOriginalRequester(makeClient, runStore, yieldChecker):
    """管理员有续跑**权限**，但没有把这一轮改成"以管理员身份执行"的权力——
    否则记忆/画像写进管理员名下，是接线顺手造出来的越权面。"""
    run_id, sseBody = _parkATurn(makeClient, runStore, yieldChecker, "g-admin")
    yieldChecker._rate_limited_agents.pop(AGENT_ID, None)

    agent = _RecordingAgent()
    resp = makeClient(agent, ADMIN).post(f"/api/v1/console/chat/resume?run_id={run_id}")

    assert resp.status_code == 200
    assert agent.calls and agent.calls[0]["user_id"] == OWNER["user_id"], (
        f"管理员续跑把执行身份换成了 {agent.calls}"
    )
    assert runStore.get(run_id)["user_id"] == OWNER["user_id"], "行属主不得被改写"


def testParkedRunsAreReadableButPayloadStaysInside(makeClient, runStore, yieldChecker):
    """SSE 是一次性的：重启/刷新后"等人"这条必须还有读处，否则 parked 只写不读。
    读面回状态与原因，不回**续跑载荷**（用户原文住在那儿，只在行确实挂着时存在于库里）。

    判据落在"载荷字段不外泄"上，而不是"正文里不出现任何用户字样"：`e1067e02` 按子
    Agent 浮窗的回读需要，给投影补了 `task`（`message_digest` 就是 `intake` 存的
    task 摘要，截断到 200 字符）——那是**有意公开**的窗口标题，不是载荷本体。
    只钉"整串正文里不含任何用户字样"会把正当设计判红（假阳性会训练人忽略门禁）。
    """
    run_id, sseBody = _parkATurn(makeClient, runStore, yieldChecker, "g-read")

    body = makeClient(_RecordingAgent(), OWNER).get(
        "/api/v1/console/chat/runs", params={"session_id": "g-read"}
    ).json()
    runs = {r["run_id"]: r for r in body["data"]["runs"]}
    assert runs[run_id]["status"] == ars.PARKED_STATUS
    assert runs[run_id]["park_reason"]
    # 续跑载荷（`resume_payload`，用户原文）一律不出现在读面
    assert "resume_payload" not in runs[run_id], f"读面带出了续跑载荷：{runs[run_id]}"
    assert not any("resume_payload" in r for r in body["data"]["runs"])

    assert makeClient(_RecordingAgent(), STRANGER).get(
        "/api/v1/console/chat/runs", params={"session_id": "g-read"}
    ).status_code == 403
