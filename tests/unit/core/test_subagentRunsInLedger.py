# -*- coding: utf-8 -*-
"""H2-6 · L 条：蜂群子任务必须进 run 台账，状态面才有可回读的出口。

缺陷形态（§6-78 L 条，本批复核实状后有两处改判，写在文末）：`SwarmManager._runs`
是**进程内内存**，进程外唯一的读者是 LLM 工具 `subagent_status`（它只是把同一个内存
dict 转出去）。台账侧 `agent_run_store`/`console.py`/`chat_pipeline.py` 里
`subagent_id`/`member_session_id`/`swarm_` 零命中——**子任务在 run 台账里连一行都没有**；
而 member 直调 `agent.chat`，不经四条真回合入口，所以台账的让位/租约/终态那套一件没沾到。
后果就是用户看到的那句「刷新一下就没了」：SSE 是一次性的，窗口表是内存单例，
`MAX_FINISHED_RUNS=500` 还会静默逐出历史。

拍板形态（用户点单 A）：**接进 run 台账 + 复用既有读面**——
`_execute` 起止经台账写侧唯一落点 `agent_run_ledger` 记账（intake→晋升→终态），
新增两个可 JOIN 的键（`subagent_id` / `parent_session_id`），读面复用
`GET /console/chat/runs`（加 `scope=subagents`），不新建第二套 run 事实源（教义第 6 条：
本仓刚在 §6-12 把两份总线合一）。子任务**不参与让位闸排队**（park 对子任务没有 UI），
这条边界与它的理由写在实现注释与台账里。

两处复核改判（不是沿用旧描述）：
- 「STARTED 事件不带 status、前端硬编码 running 而后端返回 pending」——实测广播发生在
  `run.status = running` **之后**，所以那一刻后端确实是 running；真正的缺陷是
  **事件不带事实、前端只能自造事实**（竞态或重放时无从校准）。判据因此打在
  「载荷必须带 status，且值取自 run.status」上，不打在"值等于 pending"上。
- 原描述「一条卡死即整进程死锁」的另一半已由 §6-84 处理，本批只管状态面出口。

判据（缺一条这条链就是断的）：
1. 跑完一条子任务后，台账里**确有该行**，且 `session_id` 是 member 会话、
   `subagent_id`/`parent_session_id` 与蜂群那条成对（不是两个各自 uuid）；
2. 终态映射诚实：completed→completed；K 条的超时→failed + `error_type='subagent_timeout'`；
   取消→`cancelled` + `error_type='subagent_cancelled'`；
3. **重启后仍在**：换新 store 实例（等价进程重启）后，按发起者会话还能列出该子任务；
4. HTTP 出口真回读：`GET /console/chat/runs?session_id=<发起会话>&scope=subagents`
   带出该行并投出前端要用的键；`NEUROVA_RUN_GATE=off` → 503（与回合面同一口径）；
   陌生账号 → 403（归属谓词只许一处实现，不本地重写）；
5. 不新造第二套写侧：`swarm.py` 里不得出现 `INSERT/UPDATE agent_runs` 之类的本地写库，
   必须经台账那一处（AST 判 + 反向对照）；
6. STARTED 事件带 status（前端不再自造）。
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.timeout(60)

REPO = Path(__file__).resolve().parents[3]
_SWARM_FILE = REPO / "neurova" / "agent" / "swarm.py"
BUDGET_ENV = "NEUROVA_SWARM_SUBAGENT_BUDGET_SEC"
SESSION = "sess-parent-1"
USER = "u-owner"


def _memberAgent(name="蜂群成员", reply="子任务报告", *, hang=False, delay=0.0):
    agent = MagicMock()
    agent.config.name = name

    async def chat(user_input, **kw):
        if hang:
            await asyncio.Event().wait()
        if delay:
            await asyncio.sleep(delay)
        return {"text": reply}

    agent.chat = chat
    return agent


def _initiator():
    agent = MagicMock()
    agent.current_session_id = SESSION
    agent.current_user_id = USER
    return agent


@pytest.fixture()
def runStore(tmp_path, monkeypatch):
    from neurova.core import agent_run_store as ars

    monkeypatch.setenv("NEUROVA_RUN_GATE", "on")
    monkeypatch.setenv("NEUROVA_RUN_STORE_DB", str(tmp_path / "runs.db"))
    ars.reset_agent_run_store()
    # 让台账先建出来（表在，行没有）——否则"读不到行"会以 OperationalError
    # 的形态出现，红在夹具而不在行为上
    ars.get_agent_run_store()
    yield ars
    ars.reset_agent_run_store()


@pytest.fixture()
def swarm(runStore, monkeypatch):
    from neurova.agent.swarm import reset_swarm_manager, get_swarm_manager

    monkeypatch.setenv(BUDGET_ENV, "30")
    reset_swarm_manager()
    yield get_swarm_manager()
    reset_swarm_manager()


def _allLedgerRows(runStoreModule):
    """直读台账文件，**不经本批待建的新 reader**——否则红灯会红在
    `AttributeError: no attribute ...` 上，什么行为都没抓住（教义第 3 条）。"""
    import os
    import sqlite3

    conn = sqlite3.connect(os.environ["NEUROVA_RUN_STORE_DB"])
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM agent_runs").fetchall()]
    finally:
        conn.close()


async def _waitForLedgerRows(runStoreModule, expect: int, deadlineS=5.0):
    deadline = asyncio.get_running_loop().time() + deadlineS
    while True:
        rows = _allLedgerRows(runStoreModule)
        if len(rows) >= expect or asyncio.get_running_loop().time() >= deadline:
            return rows
        await asyncio.sleep(0.05)


async def _waitForTerminalLedgerRow(runStoreModule, subagentId: str, deadlineS=5.0):
    """等到那条子任务行**收尾**——等"行存在"会读到刚开的 running 行，
    判据就打不到终态映射了（这条链要证的正是终态写没写对）。"""
    from neurova.core.agent_run_store import NON_TERMINAL_STATUSES

    deadline = asyncio.get_running_loop().time() + deadlineS
    while True:
        row = next((r for r in _allLedgerRows(runStoreModule)
                    if r.get("subagent_id") == subagentId), None)
        if row is not None and row.get("status") not in NON_TERMINAL_STATUSES:
            return row
        if asyncio.get_running_loop().time() >= deadline:
            return row or {}
        await asyncio.sleep(0.05)


class TestLedgerRowExists:
    """判据 1：子任务在台账里必须有一行，且两个键成对。"""

    @pytest.mark.asyncio
    async def test_completed_subagent_has_a_ledger_row(self, swarm, runStore):
        agent = _memberAgent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            spawned = await swarm.spawn(task="写一份纪要", agent_id="m1",
                                        session_id=SESSION, background=True,
                                        initiator_agent=_initiator())
        sid = spawned["subagent_id"]
        memberSession = spawned["member_session_id"]
        rows = await _waitForLedgerRows(runStore, 1)
        assert rows, (
            "台账里一条子任务的行都没有——这就是『刷新一下就没了』的成因："
            "SSE 一次性、窗口表在内存、_runs 重启即空")
        row = next((r for r in rows if r.get("subagent_id") == sid), None)
        assert row is not None, f"按 subagent_id JOIN 不到台账行：{rows}"
        assert row["session_id"] == memberSession, (
            "台账行的会话键不是 member 那条真会话，续跑/审计就接不回同一条链")
        assert row["parent_session_id"] == SESSION
        assert (row["user_id"] or "") == USER
        assert row["status"] == "completed", row

    @pytest.mark.asyncio
    async def test_joinKeysArePairedNotTwoIndependentUuids(self, swarm, runStore):
        """L 条原话：「连手工 JOIN 的键都不成对」——这格就是它的反证。"""
        with patch("neurova.api.endpoints.get_agent_instance", return_value=_memberAgent()):
            spawned = await swarm.spawn(task="对齐键", agent_id="m1", session_id=SESSION,
                                        background=True, initiator_agent=_initiator())
        rows = await _waitForLedgerRows(runStore, 1)
        row = next((r for r in rows if r.get("subagent_id") == spawned["subagent_id"]), None)
        assert row is not None, f"按 subagent_id 找不到台账行：{rows}"
        assert swarm.status(spawned["subagent_id"])["member_session_id"] == row["session_id"]


class TestTerminalMappingIsHonest:
    """判据 2：K 条那两种收尾方式，在台账里也得是各自的成因。"""

    @pytest.mark.asyncio
    async def test_timeout_lands_failed_with_named_error_type(self, swarm, runStore, monkeypatch):
        monkeypatch.setenv(BUDGET_ENV, "0.2")
        with patch("neurova.api.endpoints.get_agent_instance",
                   return_value=_memberAgent(hang=True)):
            spawned = await swarm.spawn(task="停滞", agent_id="m1", session_id=SESSION,
                                        background=True, initiator_agent=_initiator())
        row = await _waitForTerminalLedgerRow(runStore, spawned["subagent_id"])
        assert row.get("status") == "failed", row
        assert row.get("error_type") == "subagent_timeout", row

    @pytest.mark.asyncio
    async def test_cancel_lands_cancelled_with_named_error_type(self, swarm, runStore):
        with patch("neurova.api.endpoints.get_agent_instance",
                   return_value=_memberAgent(hang=True)):
            running = asyncio.create_task(swarm.spawn(task="被取消", agent_id="m1",
                                                      session_id=SESSION, background=False,
                                                      initiator_agent=_initiator()))
            await asyncio.sleep(0.2)
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
        rows = _allLedgerRows(runStore)
        assert rows, "取消后台账里也没有行"
        assert rows[0]["status"] == "cancelled", rows[0]
        assert rows[0]["error_type"] == "subagent_cancelled", rows[0]


class TestLedgerSurvivesProcessRestart:
    """判据 3：出口的数据源必须活过进程——这正是 `_runs` 给不了的。"""

    @pytest.mark.asyncio
    async def test_new_store_instance_still_lists_the_subagent(self, swarm, runStore, tmp_path, monkeypatch):
        with patch("neurova.api.endpoints.get_agent_instance", return_value=_memberAgent()):
            spawned = await swarm.spawn(task="跨进程可见", agent_id="m1", session_id=SESSION,
                                        background=True, initiator_agent=_initiator())
        await _waitForLedgerRows(runStore, 1)
        reopened = runStore.AgentRunStore(str(tmp_path / "runs.db"))
        try:
            rows = [r for r in _allLedgerRows(runStore)
                    if r.get("subagent_id") == spawned["subagent_id"]]
            assert rows, "换新 store 实例（等价重启）后读不到这条子任务"
            assert rows[0]["status"] == "completed", rows[0]
        finally:
            reopened.close()


class TestNoSecondLedgerWriter:
    """判据 5：写库只许经台账那一处（`swarm.py` 不得自己 INSERT/UPDATE agent_runs）。"""

    def _rawSqlWrites(self, src: str) -> list[str]:
        hits = []
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value.lower()
                if ("insert into agent_runs" in text or "update agent_runs" in text
                        or "delete from agent_runs" in text):
                    hits.append(f"line {node.lineno}")
        return hits

    def test_swarm_does_not_write_the_ledger_table_itself(self):
        found = self._rawSqlWrites(_SWARM_FILE.read_text(encoding="utf-8"))
        assert not found, f"swarm.py 里出现了本地写台账：{found}——第二套写侧就是这样长出来的"

    def test_reverse_control_catches_a_local_writer(self):
        """反向对照：扫描器抓不到就是恒绿摆设（本仓老根因「扫空即全绿」）。"""
        src = 'def f(c):\n    c.execute("INSERT INTO agent_runs (run_id) VALUES (?)")\n'
        assert self._rawSqlWrites(src), "扫描器抓不到本地 INSERT agent_runs"
        assert not self._rawSqlWrites('x = "SELECT * FROM agent_runs"\n')


class TestHttpReadSurface:
    """判据 4：出口就是既有那条读面（不新建体系），归属谓词也只许一处实现。"""

    @pytest.fixture()
    def client(self, monkeypatch):
        from fastapi.testclient import TestClient

        from neurova.api.app import create_app
        from neurova.api.deps import get_current_user

        # create_app() 返回进程内缓存的同一个 app，dependency_overrides 是跨用例共享的
        # 全局态——用完必须还原（本仓踩过：上一条留下的身份会把"匿名请求"读成 403）
        app = create_app()
        previous = app.dependency_overrides.get(get_current_user, _MISSING)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": USER, "role": "admin"}
        client = TestClient(app)
        yield client
        if previous is _MISSING:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = previous

    @pytest.mark.asyncio
    async def test_runs_endpoint_lists_subagents_for_the_parent_session(
            self, client, swarm, runStore):
        with patch("neurova.api.endpoints.get_agent_instance", return_value=_memberAgent()):
            spawned = await swarm.spawn(task="出口回读", agent_id="m1", session_id=SESSION,
                                        background=True, initiator_agent=_initiator())
        await _waitForLedgerRows(runStore, 1)
        r = client.get("/api/v1/console/chat/runs",
                       params={"session_id": SESSION, "scope": "subagents"})
        assert r.status_code == 200, r.text
        runs = r.json()["data"]["runs"]
        row = next((x for x in runs if x.get("subagent_id") == spawned["subagent_id"]), None)
        assert row is not None, f"读面没带出子任务行：{runs}"
        # 前端要用的键必须投出来（与 §6-72 第五格那条 parity 守卫同口径）
        for key in ("run_id", "status", "subagent_id", "agent_id", "error_type"):
            assert key in row, f"读面少投 {key}：{row}"

    @pytest.mark.asyncio
    async def test_gate_off_returns_503_not_empty_list(self, client, monkeypatch, runStore):
        """关闸时既有回合面是 503（诚实无读面），子任务面不得改成"空列表"装成没历史。"""
        monkeypatch.setenv("NEUROVA_RUN_GATE", "off")
        r = client.get("/api/v1/console/chat/runs",
                       params={"session_id": SESSION, "scope": "subagents"})
        assert r.status_code == 503, r.text

    @pytest.mark.asyncio
    async def test_foreign_owner_is_403(self, client, swarm, runStore, monkeypatch):
        from neurova.api.deps import get_current_user

        with patch("neurova.api.endpoints.get_agent_instance", return_value=_memberAgent()):
            await swarm.spawn(task="越权探测", agent_id="m1", session_id=SESSION,
                              background=True, initiator_agent=_initiator())
        await _waitForLedgerRows(runStore, 1)
        app = client.app
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u-stranger",
                                                             "role": "user"}
        try:
            r = client.get("/api/v1/console/chat/runs",
                           params={"session_id": SESSION, "scope": "subagents"})
            assert r.status_code == 403, r.text
        finally:
            app.dependency_overrides[get_current_user] = lambda: {"user_id": USER,
                                                                 "role": "admin"}


_MISSING = object()


class TestStartedEventCarriesStatus:
    """判据 6：事件必须带事实，前端才不用自造。"""

    @pytest.mark.asyncio
    async def test_started_payload_includes_status_from_the_run(self, swarm, runStore):
        seen: list[dict] = []

        async def spyBroadcast(run, event_type, payload):
            if event_type == "subagent_started":
                seen.append(dict(payload))

        swarm._broadcast = spyBroadcast  # 只替广播出口，状态机与记账都走真的
        with patch("neurova.api.endpoints.get_agent_instance",
                   return_value=_memberAgent(delay=0.05)):
            spawned = await swarm.spawn(task="带状态", agent_id="m1", session_id=SESSION,
                                        background=True, initiator_agent=_initiator())
        await _waitForLedgerRows(runStore, 1)
        assert seen, "没有 STARTED 载荷可判"
        assert "status" in seen[0], (
            "STARTED 事件不带 status——前端只能硬编码一个值，竞态或重放时无从校准")
        assert seen[0]["status"] == "running", seen[0]
        assert spawned["subagent_id"]
