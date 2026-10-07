# -*- coding: utf-8 -*-
"""AgentRun 台账计数的读侧（台账 §6-72 第六格：`AgentRunStore.stats()` 零调用方）。

store 早就算好了四类计数（`running`/`queued`/`parked`/`terminal`，`parked` 单列是
刻意的——把它折进 terminal 就等于把"等人续跑"读成"已结束"），但全仓没有任何地方取它：
运维与用户看不到"库里还挂着几条待办"，而 `/console/tasks` 这个"运行中任务快照"端点
只给进程内的 asyncio 任务——**进程重启后那些遗留行恰好是它最该显示的东西**，
却正好不在它的读数里。

判据（改前实测不成立）：
1. `/console/tasks` 的响应里必须有 `run_ledger`，且四类计数与真库行数逐格相等；
2. parked 单列：挂起等人续跑的那条不得被算进 terminal（否则读数把"待办"说成"已完成"）。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.deps import get_current_user
from neurova.api.endpoints import console as console_mod
from neurova.core import agent_run_store as ars

pytestmark = pytest.mark.timeout(60)

USER = {"user_id": "u1", "username": "u1", "role": "user", "neuser_id": "u1"}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    db = tmp_path / "runs.db"
    monkeypatch.setenv("NEUROVA_RUN_STORE_DB", str(db))
    monkeypatch.setattr(ars, "_store", None)
    s = ars.AgentRunStore(db)
    monkeypatch.setattr(ars, "_store", s)
    yield s
    s.close()
    monkeypatch.setattr(ars, "_store", None)


@pytest.fixture()
def client(store):
    app = FastAPI()
    app.include_router(console_mod.router, prefix="/console")
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app)


def _seed(store):
    """走真状态机造三档：running / queued / parked。"""
    ridRun = store.intake("s_run", "u1", "a1", "正在跑")
    assert store.claim_next("s_run", owner="w1") == ridRun
    ridQueued = store.intake("s_run2", "u1", "a1", "还在排队")
    ridParked = store.intake("s_park", "u1", "a1", "等人续跑")
    assert store.claim_next("s_park", owner="w3") == ridParked
    assert store.park(ridParked, owner="w3", parkReason="quota_wait") is True
    return ridRun, ridQueued, ridParked


class TestRunLedgerReadout:
    def test_consoleTasksCarriesLedgerCounts(self, client, store):
        _seed(store)

        payload = client.get("/console/tasks").json()["data"]

        assert "run_ledger" in payload, (
            "台账计数没有读侧：stats() 仍是零调用方的只写不读面，"
            "运维看不到库里挂着多少待办"
        )
        counts = payload["run_ledger"]
        assert counts["running"] == 1, counts
        assert counts["queued"] == 1, counts
        assert counts["parked"] == 1, counts
        assert counts["terminal"] == 0, counts

    def test_parkedIsNotCountedAsTerminal(self, client, store):
        """parked 是"等人"不是"已结束"——折进 terminal 就是把待办说成完成。"""
        _seed(store)

        counts = client.get("/console/tasks").json()["data"]["run_ledger"]

        assert counts["terminal"] == 0, (
            f"parked 被并进了 terminal：{counts}——读数会把挂起的回合报成已收口"
        )
