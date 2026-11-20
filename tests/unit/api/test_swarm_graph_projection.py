# -*- coding: utf-8 -*-
"""P1-1 蜂群协作拓扑图投影（v2 全边集）+ P2-3 候选投影读面 测试。

覆盖（计划 §2/§5，拍板 D-A=v2 四类边 / D-C=H-4 重放投影）：
- buildSwarmGraph 纯折叠：nodes（run/审批卡/候选卡）、edges（spawn/dependency/
  approval/candidate）、meta（truncated/candidates_incomplete 诚实标注）；
- GET /console/chat/runs/{parent_session_id}/candidates：按台账取 run → 逐 run
  读事件 → 投影；鉴权/归属沿 /chat/runs 同一谓词；
- GET /console/chat/runs/{parent_session_id}/graph：同上，返回 render-ready 图。
"""

import asyncio
from typing import Any, Dict, List

import pytest
from starlette.requests import Request

from neurova.api.endpoints import console as console_module
from neurova.agent.swarm_graph_projection import buildSwarmGraph


# ---------------------------------------------------------------------------
# 造数：台账行 / H-4 事件 / 审批单 / 候选板
# ---------------------------------------------------------------------------

def row(subagentId: str, runId: str, **over: Any) -> Dict[str, Any]:
    base = {
        "run_id": runId,
        "subagent_id": subagentId,
        "session_id": f"member-{subagentId}",
        "parent_session_id": "sess-parent",
        "user_id": "u1",
        "agent_id": f"agent-{subagentId}",
        "status": "completed",
        "error_type": None,
        "team_id": "team-1",
        "started_at": 1000.0,
        "finished_at": 1100.0,
        "created_at": 999.0,
    }
    base.update(over)
    return base


def evt(sid: str, type_: str, payload: Dict[str, Any], occurredAt: str,
        lineage: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "event_id": f"evt-{sid}-{type_}",
        "type": type_,
        "subagent_id": sid,
        "causation_id": "",
        "payload": payload,
        "occurred_at": occurredAt,
        "seq": 1,
        "lineage": lineage,
    }


def lineage(parent: str = "", depth: int = 1) -> Dict[str, Any]:
    return {"parent_subagent_id": parent, "depth": depth, "agent_path": ["root", "x"],
            "team_id": "team-1", "tenant_id": "default"}


def baseGraphInputs() -> Dict[str, Any]:
    """三 run：A spawn 出 B；C 依赖 A；A 有一张 L1 审批卡；B 有一张候选卡。"""
    rows = [
        row("swarm-a", "run-a", status="completed"),
        row("swarm-b", "run-b", status="running", finished_at=None),
        row("swarm-c", "run-c", status="failed", error_type="acceptance_failed"),
    ]
    eventsByRun = {
        "swarm-a": [
            evt("swarm-a", "spawned", {"task": "A"}, "2026-11-21T10:00:00+00:00", lineage("", 1)),
            evt("swarm-a", "terminal", {"status": "completed", "duration_ms": 99999.0},
                "2026-11-21T10:01:40+00:00", lineage("", 1)),
        ],
        "swarm-b": [
            evt("swarm-b", "spawned", {"task": "B"}, "2026-11-21T10:00:05+00:00",
                lineage("swarm-a", 2)),
            # 路由的候选板来自同一事件流的投影（P2-3），这里落一条提交事件
            evt("swarm-b", "candidate_submitted",
                {"candidate_id": "cand-1", "base_revision": 1, "artifact_keys": ["k1"]},
                "2026-11-21T10:00:20+00:00", lineage("swarm-a", 2)),
        ],
        "swarm-c": [
            evt("swarm-c", "spawned", {"task": "C"}, "2026-11-21T10:00:06+00:00", lineage("", 1)),
        ],
    }
    memberProfiles = {
        "swarm-a": {"member_name": "Alice", "kind": "internal", "executor_tool": ""},
        "swarm-b": {"member_name": "外部Claude", "kind": "external", "executor_tool": "claude-code"},
        "swarm-c": {"member_name": "Carol", "kind": "internal", "executor_tool": ""},
    }
    taskUnits = {
        "swarm-c": {"goal": "C", "dependencies": ["swarm-a"]},
    }
    approvals = [
        {"request_id": "req-1", "run_id": "swarm-a", "level": "L1",
         "operation": "merge_candidate:cand-x", "status": "decided",
         "decision": "approve", "decided_by": "u1",
         "requested_at": 1005.0, "decided_at": 1010.0},
    ]
    candidateBoard = {
        "revision": 2,
        "incomplete": False,
        "candidates": [
            {"candidate_id": "cand-1", "run_id": "swarm-b", "artifact_keys": ["k1"],
             "base_revision": 1, "status": "submitted", "conflict_with": [],
             "note": "", "created_at": "2026-11-21T10:00:20+00:00", "decided_at": ""},
        ],
        "conflicts": [],
    }
    return {
        "runRows": rows,
        "eventsByRun": eventsByRun,
        "memberProfiles": memberProfiles,
        "taskUnits": taskUnits,
        "approvals": approvals,
        "candidateBoard": candidateBoard,
    }


# ---------------------------------------------------------------------------
# buildSwarmGraph 纯折叠
# ---------------------------------------------------------------------------

class TestBuildSwarmGraph:
    def test_v2_nodes_and_all_four_edge_types(self):
        graph = buildSwarmGraph(**baseGraphInputs())
        assert set(graph.keys()) == {"nodes", "edges", "meta"}

        runNodes = {n["id"]: n for n in graph["nodes"] if n["nodeType"] == "run"}
        assert set(runNodes) == {"swarm-a", "swarm-b", "swarm-c"}
        a = runNodes["swarm-a"]
        # 节点字段集钉死（P2-4 服务端单源）
        assert set(a.keys()) == {
            "id", "nodeType", "run_id", "member_name", "kind", "executor_tool",
            "status", "depth", "team_id", "started_at", "finished_at",
            "duration_ms", "error_type", "level", "decision", "decided_by",
            "request_id", "candidate_id", "artifact_keys", "base_revision", "note"}
        assert a["run_id"] == "run-a"
        assert a["member_name"] == "Alice"
        assert a["kind"] == "internal"
        assert a["status"] == "completed"
        assert a["depth"] == 1
        assert a["duration_ms"] == pytest.approx(100000.0)
        b = runNodes["swarm-b"]
        assert b["kind"] == "external" and b["executor_tool"] == "claude-code"
        assert b["depth"] == 2
        c = runNodes["swarm-c"]
        assert c["status"] == "failed" and c["error_type"] == "acceptance_failed"

        edges = graph["edges"]
        byType: Dict[str, List[Dict[str, Any]]] = {}
        for e in edges:
            byType.setdefault(e["type"], []).append(e)
        assert set(byType) == {"spawn", "dependency", "approval", "candidate"}
        spawn = byType["spawn"][0]
        assert (spawn["from"], spawn["to"]) == ("swarm-a", "swarm-b")
        dep = byType["dependency"][0]
        assert (dep["from"], dep["to"]) == ("swarm-a", "swarm-c")
        appr = byType["approval"][0]
        assert appr["from"] == "swarm-a"
        assert appr["to"].startswith("approval:")
        assert appr["level"] == "L1" and appr["decision"] == "approve"
        cand = byType["candidate"][0]
        assert cand["from"] == "swarm-b"
        assert cand["to"] == "candidate:cand-1"
        assert cand["status"] == "submitted"

        # 审批卡/候选卡节点形态
        cards = {n["id"]: n for n in graph["nodes"] if n["nodeType"] != "run"}
        assert set(cards) == {"approval:req-1", "candidate:cand-1"}
        assert cards["approval:req-1"]["status"] == "approved"
        assert cards["approval:req-1"]["decided_by"] == "u1"
        assert cards["candidate:cand-1"]["status"] == "submitted"
        assert cards["candidate:cand-1"]["artifact_keys"] == ["k1"]

        meta = graph["meta"]
        assert meta["truncated"] is False
        assert meta["candidates_incomplete"] is False
        assert meta["revision"] == 2

    def test_truncated_marked_honestly(self):
        inputs = baseGraphInputs()
        graph = buildSwarmGraph(maxNodes=2, **inputs)
        assert graph["meta"]["truncated"] is True
        runIds = {n["id"] for n in graph["nodes"] if n["nodeType"] == "run"}
        assert len(runIds) == 2

    def test_dependency_edges_absent_after_restart_without_memory(self):
        """重启后内存 task_unit 缺席：依赖边如实缺（不凭空补），其余边照常。"""
        inputs = baseGraphInputs()
        inputs["taskUnits"] = None
        graph = buildSwarmGraph(**inputs)
        assert not [e for e in graph["edges"] if e["type"] == "dependency"]
        assert [e for e in graph["edges"] if e["type"] == "spawn"]

    def test_dangling_references_not_emitted(self):
        """parent/依赖指向不存在的 run：不吐悬空边（vue-flow 会丢弃），meta 计数诚实。"""
        inputs = baseGraphInputs()
        inputs["eventsByRun"]["swarm-b"] = [
            evt("swarm-b", "spawned", {"task": "B"}, "2026-11-21T10:00:05+00:00",
                lineage("swarm-ghost", 2))]
        inputs["taskUnits"] = {"swarm-c": {"dependencies": ["swarm-ghost"]}}
        graph = buildSwarmGraph(**inputs)
        assert not [e for e in graph["edges"] if e["type"] in ("spawn", "dependency")]
        assert graph["meta"]["counts"]["danglingEdges"] == 2

    def test_candidates_incomplete_propagates(self):
        inputs = baseGraphInputs()
        inputs["candidateBoard"] = {**inputs["candidateBoard"], "incomplete": True}
        graph = buildSwarmGraph(**inputs)
        assert graph["meta"]["candidates_incomplete"] is True

    def test_empty_session_projects_empty_graph(self):
        graph = buildSwarmGraph(runRows=[], eventsByRun={})
        assert graph["nodes"] == [] and graph["edges"] == []
        assert graph["meta"]["truncated"] is False


# ---------------------------------------------------------------------------
# 端点：GET /console/chat/runs/{parent_session_id}/candidates 与 /graph
# ---------------------------------------------------------------------------

def _make_request() -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request({"type": "http", "method": "GET", "path": "/chat/runs",
                    "headers": []}, receive=receive)


ADMIN = {"user_id": "u1", "username": "u1", "role": "admin", "neuser_id": "u1"}
OTHER = {"user_id": "u2", "username": "u2", "role": "user", "neuser_id": "u2"}


@pytest.fixture
def gateOn(monkeypatch):
    from neurova.core import agent_run_store as ars

    monkeypatch.setattr(ars, "run_gate_enabled", lambda: True)


def _patchStore(monkeypatch, rows: List[Dict[str, Any]]) -> None:
    from neurova.core import agent_run_store as ars

    class FakeStore:
        def list_subagent_runs(self, parentSessionId, limit=20):
            return list(rows)

    monkeypatch.setattr(ars, "get_agent_run_store", lambda: FakeStore())


def _patchEvents(monkeypatch, eventsByRun: Dict[str, List[Dict[str, Any]]]) -> None:
    import neurova.agent.swarm_event_log as sel

    monkeypatch.setattr(sel, "readRunEvents",
                        lambda sid: list(eventsByRun.get(sid, [])))


class TestCandidatesEndpoint:
    def test_returns_replay_projection(self, monkeypatch, gateOn):
        inputs = baseGraphInputs()
        _patchStore(monkeypatch, inputs["runRows"])
        _patchEvents(monkeypatch, {
            "swarm-b": [
                evt("swarm-b", "candidate_submitted",
                    {"candidate_id": "cand-1", "base_revision": 0,
                     "artifact_keys": ["k1"]},
                    "2026-11-21T10:00:20+00:00", lineage("swarm-a", 2)),
            ],
        })
        resp = asyncio.run(console_module.get_console_run_candidates(
            "sess-parent", _make_request(), 200, ADMIN))
        data = resp["data"]
        assert data["parent_session_id"] == "sess-parent"
        assert data["source"] == "replay"
        assert data["candidates"][0]["candidate_id"] == "cand-1"
        assert data["candidates"][0]["status"] == "submitted"

    def test_ownership_fail_closed_for_non_admin(self, monkeypatch, gateOn):
        inputs = baseGraphInputs()
        rows = [row("swarm-a", "run-a", user_id="u1")]
        _patchStore(monkeypatch, rows)
        _patchEvents(monkeypatch, {})
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            asyncio.run(console_module.get_console_run_candidates(
                "sess-parent", _make_request(), 200, OTHER))
        assert exc.value.status_code == 403

    def test_gate_off_returns_503(self, monkeypatch):
        from neurova.core import agent_run_store as ars

        monkeypatch.setattr(ars, "run_gate_enabled", lambda: False)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            asyncio.run(console_module.get_console_run_candidates(
                "sess-parent", _make_request(), 200, ADMIN))
        assert exc.value.status_code == 503


class TestGraphEndpoint:
    def test_returns_render_ready_graph(self, monkeypatch, gateOn):
        inputs = baseGraphInputs()
        _patchStore(monkeypatch, inputs["runRows"])
        _patchEvents(monkeypatch, inputs["eventsByRun"])
        monkeypatch.setattr(console_module, "_graphMemberProfiles",
                            lambda rows: inputs["memberProfiles"])
        monkeypatch.setattr(console_module, "_graphTaskUnits",
                            lambda rows: inputs["taskUnits"])
        monkeypatch.setattr(console_module, "_graphApprovalRecords",
                            lambda sids: inputs["approvals"])
        resp = asyncio.run(console_module.get_console_run_graph(
            "sess-parent", _make_request(), 200, ADMIN))
        data = resp["data"]
        assert {n["id"] for n in data["nodes"] if n["nodeType"] == "run"} == \
            {"swarm-a", "swarm-b", "swarm-c"}
        edgeTypes = {e["type"] for e in data["edges"]}
        assert edgeTypes == {"spawn", "dependency", "approval", "candidate"}
        assert data["meta"]["truncated"] is False

    def test_ownership_fail_closed_for_non_admin(self, monkeypatch, gateOn):
        rows = [row("swarm-a", "run-a", user_id="u1")]
        _patchStore(monkeypatch, rows)
        _patchEvents(monkeypatch, {})
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            asyncio.run(console_module.get_console_run_graph(
                "sess-parent", _make_request(), 200, OTHER))
        assert exc.value.status_code == 403
