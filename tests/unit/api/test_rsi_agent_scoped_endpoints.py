"""RSI 审批面按 agent 定位（工单 011 的后端半张）。

审计实测的串写：`RSIOrchestrator` 按 agent 构造（agent_core），却又把实例写进
**进程级单例属性**，后构造者覆盖；而端点只读那个单例属性 ⇒ 永远是"最后构造的
agent"的编排器，与同文件 `_get_agent()` 指向的对象都不是一个。后果不是"看不见"，
是**批准作用在错误的 agent 上**（提案台账已按 agent 分域，装库更是装到别人家）。

本套件钉四件事：

1. 三个 RSI 端点都接受 `agent_id` 并经与 `_get_agent()` 同源的定位器取编排器；
   指名 agent 而该 agent 不在池中时**不得回落**到别的 agent —— 回落就是本单要拆的缺陷。
2. 未装配 RSI ⇒ 503 + 原因。取消 `available:false` 的静默 200：
   "没装配"与"跑了一轮什么都没改"是两件相反的运维事实。
3. 全状态列表 `GET /rsi/proposals?state=`（默认 `all`）——只有 PENDING 可见时，
   批准过什么、结果如何永久消失，回滚与审计无从进行。
4. 反向锁：`governance.py` 里不再有"读进程级单例属性"这条路径。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.deps import get_current_user
from neurova.api.endpoints.governance import router


class _State:
    """替 `AppState`：`get_agent(agent_id)` 与真实现同签名，池子里只有被登记的那些。"""

    def __init__(self, agents, default_agent_id=None):
        self.agents = agents
        self.default_agent_id = default_agent_id or next(iter(agents), None)

    def get_agent(self, agent_id: str = None):
        return self.agents.get(agent_id or self.default_agent_id)


class _Agent:
    def __init__(self, orchestrator):
        self.rsi_orchestrator = orchestrator


class _FakeProposer:
    def __init__(self, proposals):
        self._proposals = proposals

    def list_pending_proposals(self):
        return [p for p in self._proposals if p.status is _Status.PENDING]

    def list_all_proposals(self):
        return list(self._proposals)


class _FakeOrchestrator:
    def __init__(self, agent_id, proposals):
        self.agent_id = agent_id
        self.self_improvement_proposer = _FakeProposer(proposals)

    def get_status(self):
        return {"agent_id": self.agent_id, "deployment_phase": 2}


class _Status(str, Enum):
    PENDING = "pending"
    APPLIED = "applied"


@dataclass
class _Proposal:
    """与 `ImprovementProposal` 同形的最小假对象：端点吃的是对象契约（.status/.to_dict()），
    喂 dict 会让本套件的断言测到一条生产里不存在的路径。"""

    proposal_id: str
    status: _Status
    target: str = "rsi-fix"
    agent_id: str = ""

    def to_dict(self):
        return {
            "proposal_id": self.proposal_id,
            "status": self.status.value,
            "target": self.target,
            "agent_id": self.agent_id,
        }


def _proposal(pid, status="pending", target="rsi-fix"):
    return _Proposal(pid, _Status(status), target)


def _client(state, monkeypatch):
    from neurova.api import endpoints as endpoints_pkg

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/governance")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "admin1", "role": "admin"}
    monkeypatch.setattr(endpoints_pkg, "get_app_state", lambda: state)
    return TestClient(app)


KAI = [_proposal("prop-kai-1"), _proposal("prop-kai-2", status="applied")]
LING = [_proposal("prop-ling-1")]


def _two_agent_state(monkeypatch):
    state = _State({"kai": _Agent(_FakeOrchestrator("kai", KAI)),
                    "yi_ling": _Agent(_FakeOrchestrator("yi_ling", LING))},
                   default_agent_id="kai")
    return _client(state, monkeypatch)


def test_pending_endpoint_is_scoped_to_the_named_agent(monkeypatch):
    """?agent_id= 取到的是各自那一份，不是"最后构造的 agent"。"""
    client = _two_agent_state(monkeypatch)

    kai = client.get("/api/v1/governance/rsi/proposals/pending?agent_id=kai")
    ling = client.get("/api/v1/governance/rsi/proposals/pending?agent_id=yi_ling")

    assert kai.status_code == 200 and ling.status_code == 200
    kai_ids = [p["proposal_id"] for p in kai.json()["data"]["proposals"]]
    ling_ids = [p["proposal_id"] for p in ling.json()["data"]["proposals"]]
    assert kai_ids == ["prop-kai-1"], kai_ids
    assert ling_ids == ["prop-ling-1"], ling_ids


def test_unknown_agent_does_not_fall_back_to_another_agents_orchestrator(monkeypatch):
    """指名一个不在池里的 agent ⇒ 503，绝不回落到"随便某个 agent 的编排器"。"""
    client = _two_agent_state(monkeypatch)

    resp = client.get("/api/v1/governance/rsi/proposals/pending?agent_id=nobody")

    assert resp.status_code == 503, f"{resp.status_code} {resp.text[:200]}"
    assert "nobody" in resp.json()["detail"], resp.json()


def test_absent_rsi_is_503_not_a_quiet_empty_200(monkeypatch):
    """未装配必须 503：`available:false` 的静默 200 会把"没装配"读成"一切正常"。"""
    client = _client(_State({"kai": _Agent(None)}), monkeypatch)

    resp = client.get("/api/v1/governance/rsi/proposals/pending")

    assert resp.status_code == 503, f"{resp.status_code} {resp.text[:200]}"
    assert "503" != "" and resp.json()["detail"], resp.json()

    status = client.get("/api/v1/governance/rsi/status")
    assert status.status_code == 503, status.text[:200]


def test_all_state_list_endpoint_filters_by_state(monkeypatch):
    """全状态列表：默认 all、可按 state 收窄，非法 state 由 FastAPI 挡下。"""
    client = _two_agent_state(monkeypatch)

    everything = client.get("/api/v1/governance/rsi/proposals?agent_id=kai")
    applied = client.get("/api/v1/governance/rsi/proposals?agent_id=kai&state=applied")
    bogus = client.get("/api/v1/governance/rsi/proposals?agent_id=kai&state=whatever")

    assert everything.status_code == 200, everything.text
    ids = {p["proposal_id"] for p in everything.json()["data"]["proposals"]}
    assert ids == {"prop-kai-1", "prop-kai-2"}, ids
    assert applied.status_code == 200
    assert [p["proposal_id"] for p in applied.json()["data"]["proposals"]] == ["prop-kai-2"]
    assert bogus.status_code == 422, bogus.status_code


def test_reject_endpoint_is_scoped_to_the_named_agent(monkeypatch):
    """reject 也必须落在被指名的 agent 上（三个端点同一个定位器，不各修一处）。"""
    state_ling_rejected = []
    ling_orch = _FakeOrchestrator("yi_ling", LING)

    class _RejectingProposer(_FakeProposer):
        def reject_proposal(self, proposal_id, reason=""):
            state_ling_rejected.append((self is ling_orch.self_improvement_proposer, proposal_id))
            return True

    ling_orch.self_improvement_proposer = _RejectingProposer(LING)
    client = _client(_State({"kai": _Agent(_FakeOrchestrator("kai", KAI)),
                            "yi_ling": _Agent(ling_orch)}), monkeypatch)

    resp = client.post(
        "/api/v1/governance/rsi/proposals/prop-ling-1/reject?agent_id=yi_ling",
        json={"reason": "不予采纳"},
    )

    assert resp.status_code == 200, resp.text
    assert state_ling_rejected and state_ling_rejected[0] == (True, "prop-ling-1"), (
        f"拒绝动作没落在 yi_ling 的 proposer 上：{state_ling_rejected}")


def test_approve_endpoint_uses_the_same_locator(monkeypatch):
    """approve 走同一个定位器；未指名时用默认 agent（与 _get_agent() 同源）。"""
    seen = {}
    orch = _FakeOrchestrator("kai", KAI)

    class _ApprovingProposer(_FakeProposer):
        def approve_and_apply(self, proposal_id, approver="", tool_sequence=None):
            seen["args"] = (proposal_id, approver, tuple(tool_sequence or ()))
            return None  # 让端点按失败分支回 409，本用例只验定位

    orch.self_improvement_proposer = _ApprovingProposer(KAI)
    client = _client(_State({"kai": _Agent(orch)}), monkeypatch)

    resp = client.post(
        "/api/v1/governance/rsi/proposals/prop-kai-1/approve",
        json={"approved_by": "admin", "tool_sequence": ["read_memory"]},
    )

    assert resp.status_code == 409, resp.text
    assert seen["args"] == ("prop-kai-1", "admin", ("read_memory",)), seen


def test_governance_module_no_longer_reads_the_process_singleton():
    """反向锁：读 `get_evolution_orchestrator().rsi_orchestrator` 那条路必须拆掉。"""
    import ast
    from pathlib import Path

    path = Path("neurova/api/endpoints/governance.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # 只看可执行代码里的名字使用：docstring 引用"被拆掉的历史实现"是正当的
    used = [
        node.id for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "get_evolution_orchestrator"
    ] + [
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "get_evolution_orchestrator"
    ]
    assert not used, (
        "仍在读进程级单例属性：后构造的 agent 会覆盖它，审批于是作用在错误的 agent 上")
