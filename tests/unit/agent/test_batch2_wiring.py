# -*- coding: utf-8 -*-
"""批二接线集成测试：A2 事件库双写镜像 / A5 闲置 run 结算 / D2 组织权限天花板。

- A2：_logRunEvent 统一写点镜像进全局事件库（fail-open，账本仍是一手事实源）；
- A5：settleIdleRuns 按护栏结算闲置终态 run（逐出内存台账 + auto_settled 留痕，
  不新增状态词）；开关 NEUROVA_SWARM_AUTO_SETTLE 默认关；
- D2：delegatedModeScope 把生效模式经 NEUROVA_PERMISSION_CEILING 封顶后再入继承链。
"""
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import neurova.agent.swarm as swarm_module
from neurova.agent.swarm import (
    SubAgentRun,
    get_swarm_manager,
    reset_swarm_manager,
)
from neurova.security.permission_mode import PermissionMode


@pytest.fixture
def swarm():
    reset_swarm_manager()
    return get_swarm_manager()


@pytest.fixture
def event_store(tmp_path, monkeypatch):
    from neurova.agent.swarm_event_store import SwarmEventStore

    store = SwarmEventStore(str(tmp_path / "event_store.db"))
    monkeypatch.setattr(swarm_module, "_eventStore", lambda: store)
    return store


def _run(sid="run-x", status="completed", finished_at=None, approvals=None):
    run = SubAgentRun(
        subagent_id=sid, depth=1, agent_id="agent-a", agent_name="A",
        task="样例任务", origin="chat", status=status, report="产出",
        finished_at=finished_at if finished_at is not None else time.time(),
    )
    if approvals:
        run.approvals.extend(approvals)
    return run


class TestEventMirror:
    def test_log_run_event_mirrors_into_store(self, swarm, event_store):
        run = _run("run-mir")
        swarm._logRunEvent(run, "spawned", {"task": "样例"})
        events = event_store.readStream("run-mir")
        assert len(events) == 1
        assert events[0]["type"] == "spawned"
        assert events[0]["event_id"] == run.last_event_id
        # JSONL 一手账本同样在
        jsonl = swarm.runEvents("run-mir")["events"]
        assert len(jsonl) == 1

    def test_mirror_fail_open_keeps_ledger(self, swarm, monkeypatch):
        def boom():
            raise RuntimeError("store broken")

        monkeypatch.setattr(swarm_module, "_eventStore", boom)
        run = _run("run-mir2")
        swarm._logRunEvent(run, "spawned", {"task": "t"})  # 不抛
        assert len(swarm.runEvents("run-mir2")["events"]) == 1

    def test_multiple_events_keep_global_order(self, swarm, event_store):
        run = _run("run-mir3")
        for i in range(3):
            swarm._logRunEvent(run, "member_chunk", {"n": i})
        seqs = [e["seq"] for e in event_store.readStream("run-mir3")]
        assert seqs == sorted(seqs) and len(seqs) == 3


class TestSettleIdleRuns:
    def test_disabled_by_default(self, swarm, monkeypatch):
        monkeypatch.setenv("NEUROVA_SWARM_AUTO_SETTLE", "")
        result = swarm.settleIdleRuns()
        assert result == {"enabled": False, "settled": [], "skipped": [], "failed": []}

    def test_settles_old_finished_run(self, swarm, monkeypatch):
        monkeypatch.setenv("NEUROVA_SWARM_AUTO_SETTLE", "1")
        now = time.time()
        run = _run("run-old", finished_at=now - 4 * 86400)
        with swarm._lock:
            swarm._runs["run-old"] = run
        result = swarm.settleIdleRuns(now_ts=now)
        assert "run-old" in result["settled"], result
        assert "run-old" not in swarm._runs, "结算=逐出内存台账"
        events = swarm.runEvents("run-old")["events"]
        assert any(e["type"] == "auto_settled" for e in events)

    def test_pending_approval_guard(self, swarm, monkeypatch):
        monkeypatch.setenv("NEUROVA_SWARM_AUTO_SETTLE", "1")
        now = time.time()
        run = _run("run-appr", finished_at=now - 4 * 86400,
                   approvals=[{"status": "pending", "action": "acp:Bash:execute"}])
        with swarm._lock:
            swarm._runs["run-appr"] = run
        result = swarm.settleIdleRuns(now_ts=now)
        assert any(s[0] == "run-appr" and s[1] == "pending_approval"
                   for s in result["skipped"]), result
        assert "run-appr" in swarm._runs, "pending 审批的 run 不得被结算"

    def test_grace_period_guard(self, swarm, monkeypatch):
        monkeypatch.setenv("NEUROVA_SWARM_AUTO_SETTLE", "1")
        now = time.time()
        run = _run("run-fresh", finished_at=now - 30)
        with swarm._lock:
            swarm._runs["run-fresh"] = run
        result = swarm.settleIdleRuns(now_ts=now)
        assert any(s[0] == "run-fresh" and s[1] == "grace_period"
                   for s in result["skipped"]), result
        assert "run-fresh" in swarm._runs

    def test_running_run_never_candidate(self, swarm, monkeypatch):
        monkeypatch.setenv("NEUROVA_SWARM_AUTO_SETTLE", "1")
        now = time.time()
        run = _run("run-live", status="running", finished_at=now - 400 * 86400)
        with swarm._lock:
            swarm._runs["run-live"] = run
        result = swarm.settleIdleRuns(now_ts=now)
        assert all(s[0] != "run-live" for s in result["skipped"])
        assert "run-live" in swarm._runs


class TestDelegatedModeScope:
    def test_org_ceiling_narrows(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_PERMISSION_CEILING", "guarded")
        monkeypatch.setattr(
            "neurova.security.permission_mode.resolvePermissionModeFor",
            lambda agentId, settings=None: PermissionMode.YOLO,
        )
        from neurova.security.permission_mode import effectiveModeInContext
        from neurova.tool_executor import delegatedModeScope

        agent = SimpleNamespace(config=SimpleNamespace(agent_id="ceil-1"))
        with delegatedModeScope(agent):
            assert effectiveModeInContext() == PermissionMode.GUARDED

    def test_no_ceiling_keeps_mode(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_PERMISSION_CEILING", raising=False)
        monkeypatch.setattr(
            "neurova.security.permission_mode.resolvePermissionModeFor",
            lambda agentId, settings=None: PermissionMode.YOLO,
        )
        from neurova.security.permission_mode import effectiveModeInContext
        from neurova.tool_executor import delegatedModeScope

        agent = SimpleNamespace(config=SimpleNamespace(agent_id="ceil-2"))
        with delegatedModeScope(agent):
            assert effectiveModeInContext() == PermissionMode.YOLO

    def test_ceiling_does_not_widen_stricter_parent(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_PERMISSION_CEILING", "build")
        monkeypatch.setattr(
            "neurova.security.permission_mode.resolvePermissionModeFor",
            lambda agentId, settings=None: PermissionMode.YOLO,
        )
        from neurova.security.permission_mode import (
            effectiveModeInContext,
            inheritedModeScope,
        )
        from neurova.tool_executor import delegatedModeScope

        agent = SimpleNamespace(config=SimpleNamespace(agent_id="ceil-3"))
        # 父链已是 GUARDED（更严）：天花板 BUILD 不得把它放宽
        with inheritedModeScope(PermissionMode.GUARDED):
            with delegatedModeScope(agent):
                assert effectiveModeInContext() == PermissionMode.GUARDED
