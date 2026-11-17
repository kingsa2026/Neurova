# -*- coding: utf-8 -*-
"""S8 审批审计持久化（超越方案 S8 批，评测 E1 反超点）。

覆盖：
- requestRunApproval / decideSwarmApproval 的每次请求/决定落审计事件
  （复用仓内审计单源 neurova.security.audit_logger，S7 memory_admission 同源）；
- 一次 L2 审批从请求到决定产生两条可查审计事件（请求+决定），字段齐全：
  级别、动作、path_values、发起 run、决策人、决策、时延；
- fail-open：审计写失败不阻断审批主流程，错误经日志 + 计数可见；
- 查询面：GET /api/v1/audit/approvals?run_id=... 按 runId 拉完整审批轨迹
  （请求+决定成对展示；挂既有 /v1/audit 管理查询域，admin 门与同域一致）。
"""

import logging
import os

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_approval_audit_0123456789")

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.agent.approval_chain import (
    approvalAuditCounters,
    decideSwarmApproval,
    requestRunApproval,
)
from neurova.agent.swarm import SubAgentRun, reset_swarm_manager
from neurova.security.audit_logger import AuditEventType, AuditSeverity, AuditLogger
from neurova.security.approval_manager import ApprovalManager
from neurova.security.approval_relay import installApprovalRelay

MOCK_ADMIN = {"user_id": "a1", "username": "admin1", "role": "admin"}


@pytest.fixture
def swarmRun():
    reset_swarm_manager()
    return SubAgentRun(
        agent_id="child", agent_name="子代理", task="整理季度数据",
        session_id="parent-session", origin="chat", member_session_id="swarm_member_audit",
    )


@pytest.fixture
def approvals(tmp_path, monkeypatch):
    """真 ApprovalManager（临时数据根）+ 中继；patch 单源工厂入口。"""
    monkeypatch.setenv("NEUROVA_SWARM_APPROVAL_WAIT_S", "3")
    mgr = ApprovalManager(str(tmp_path / "approval_ws"))
    assert installApprovalRelay(mgr) is True
    with patch("neurova.security.approval_manager.get_approval_manager", return_value=mgr):
        yield mgr


@pytest.fixture
def parentMail():
    box = MagicMock()
    with patch("neurova.agent.mailbox.get_agent_mailbox", return_value=box):
        yield box


@pytest.fixture
def auditDb(tmp_path):
    """审计单例整体重定向到 tmp_path（log_audit 与查询同落这份）。"""
    import neurova.security.audit_logger as auditModule

    savedInstance = auditModule.AuditLogger._instance
    savedGlobal = auditModule._audit_logger
    auditModule.AuditLogger._instance = None
    auditModule._audit_logger = None
    try:
        auditLogger = auditModule.AuditLogger(db_path=str(tmp_path / "audit.db"))
        auditModule._audit_logger = auditLogger
        yield auditLogger
    finally:
        auditModule.AuditLogger._instance = savedInstance
        auditModule._audit_logger = savedGlobal


class TestRequestAndDecisionAudit:
    @pytest.mark.asyncio
    async def test_l2_request_and_decision_produce_two_queryable_events(
        self, swarmRun, approvals, parentMail, auditDb
    ):
        result = await requestRunApproval(
            swarmRun, "删除生产数据库表", reason="清理过期分区", level="L2"
        )
        assert result["approved"] is False and result["pending"] is True
        requestId = result["request_id"]
        decision = decideSwarmApproval(requestId, "approve", note="同意清理")
        assert decision["success"] is True

        events = auditDb.query(
            event_type=AuditEventType.APPROVAL, resource_id=swarmRun.subagent_id
        )
        assert len(events) == 2, f"请求+决定应各落一条审计事件，实得 {len(events)}"
        byPhase = {e.details.get("phase"): e for e in events}
        requestEvent = byPhase.get("request")
        decideEvent = byPhase.get("decide")
        assert requestEvent is not None and decideEvent is not None

        # ── 请求事件：级别、动作、path_values、发起 run ──
        assert requestEvent.action == "swarm_approval_request"
        assert requestEvent.severity == AuditSeverity.HIGH, "L2 审计级别必须是 high"
        assert requestEvent.user_id == swarmRun.agent_id
        assert requestEvent.resource_type == "swarm_approval"
        assert requestEvent.resource_id == swarmRun.subagent_id
        details = requestEvent.details
        assert details["request_id"] == requestId
        assert details["run_id"] == swarmRun.subagent_id
        assert details["agent_id"] == swarmRun.agent_id
        assert details["level"] == "L2"
        assert details["effective_level"] == "L2"
        assert details["operation"] == "删除生产数据库表"
        assert details["decision"] == "pending"
        pathValues = [list(p) for p in details["path_values"]]
        assert ["run_id", swarmRun.subagent_id] in pathValues
        assert ["request_id", requestId] in pathValues
        assert isinstance(details["latency_ms"], (int, float))

        # ── 决定事件：决策人、决策、时延 ──
        assert decideEvent.action == "swarm_approval_decide"
        assert decideEvent.details["request_id"] == requestId
        assert decideEvent.details["decision"] == "approve"
        assert decideEvent.details["decided_by"] == "parent_agent"
        assert decideEvent.user_id == "parent_agent"
        assert decideEvent.details["note"] == "同意清理"
        assert isinstance(decideEvent.details["latency_ms"], (int, float))
        assert decideEvent.details["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_reject_decision_audited(
        self, swarmRun, approvals, parentMail, auditDb
    ):
        result = await requestRunApproval(swarmRun, "批量外发邮件", level="L2")
        requestId = result["request_id"]
        decision = decideSwarmApproval(requestId, "reject", note="风险大")
        assert decision["success"] is True
        events = auditDb.query(
            event_type=AuditEventType.APPROVAL, resource_id=swarmRun.subagent_id
        )
        decideEvents = [e for e in events if e.details.get("phase") == "decide"]
        assert len(decideEvents) == 1
        assert decideEvents[0].details["decision"] == "reject"
        assert decideEvents[0].details["note"] == "风险大"

    @pytest.mark.asyncio
    async def test_l0_auto_approve_emits_request_and_decision_events(
        self, swarmRun, approvals, parentMail, auditDb
    ):
        result = await requestRunApproval(swarmRun, "读取只读配置", level="L0")
        assert result["approved"] is True and result["auto_approved"] is True
        events = auditDb.query(
            event_type=AuditEventType.APPROVAL, resource_id=swarmRun.subagent_id
        )
        phases = sorted(e.details["phase"] for e in events)
        assert phases == ["decide", "request"], "自动放行也是一次决定，请求+决定都要留痕"
        decideEvent = [e for e in events if e.details["phase"] == "decide"][0]
        assert decideEvent.details["decision"] == "approve"
        assert decideEvent.details["decided_by"] == "auto_rule:L0"
        assert decideEvent.severity == AuditSeverity.LOW
        # resource_id 过滤是精确匹配：别的 run 查不到
        assert auditDb.query(event_type=AuditEventType.APPROVAL, resource_id="其他run") == []


class TestAuditFailureFailOpen:
    @pytest.mark.asyncio
    async def test_request_survives_audit_write_failure(
        self, swarmRun, approvals, parentMail, auditDb, monkeypatch, caplog
    ):
        import neurova.security.audit_logger as auditModule

        def boom(*args, **kwargs):
            raise RuntimeError("audit db down")

        monkeypatch.setattr(auditModule, "log_audit", boom)
        before = approvalAuditCounters().get("auditWriteFailures", 0)
        with caplog.at_level(logging.ERROR, logger="neurova.agent.approval_chain"):
            result = await requestRunApproval(swarmRun, "读取只读配置", level="L0")
        assert result["approved"] is True, "审计写失败不得阻断审批主流程（fail-open）"
        after = approvalAuditCounters().get("auditWriteFailures", 0)
        assert after > before, "审计写失败必须计数可见（L0 流程请求+决定各写一次）"
        assert "审批审计" in caplog.text, "审计写失败必须进错误日志"

    @pytest.mark.asyncio
    async def test_decide_survives_audit_write_failure(
        self, swarmRun, approvals, parentMail, auditDb, monkeypatch, caplog
    ):
        result = await requestRunApproval(swarmRun, "批量外发邮件", level="L2")
        requestId = result["request_id"]
        import neurova.security.audit_logger as auditModule

        monkeypatch.setattr(auditModule, "log_audit", lambda *a, **k: False)
        before = approvalAuditCounters().get("auditWriteFailures", 0)
        with caplog.at_level(logging.ERROR, logger="neurova.agent.approval_chain"):
            decision = decideSwarmApproval(requestId, "approve")
        assert decision["success"] is True, "审计写失败不得阻断裁决主流程"
        assert approvalAuditCounters().get("auditWriteFailures", 0) == before + 1
        assert "审批审计" in caplog.text


class TestTrajectoryEndpoint:
    @pytest.fixture()
    def auditApp(self, auditDb, monkeypatch):
        from neurova.api.endpoints import audit as auditApi

        monkeypatch.setattr(auditApi, "get_audit_logger", lambda *a, **k: auditDb)
        app = FastAPI()
        app.include_router(auditApi.router, prefix="/api/v1/audit")
        return app

    @pytest.mark.asyncio
    async def test_trajectory_pairs_request_and_decision_by_run_id(
        self, swarmRun, approvals, parentMail, auditDb, auditApp
    ):
        from tests.auth_headers import overrideIdentity

        result = await requestRunApproval(
            swarmRun, "删除生产数据库表", reason="清理过期分区", level="L2"
        )
        requestId = result["request_id"]
        assert decideSwarmApproval(requestId, "approve", note="同意")["success"] is True

        overrideIdentity(auditApp, MOCK_ADMIN)
        with TestClient(auditApp) as client:
            resp = client.get(
                "/api/v1/audit/approvals", params={"run_id": swarmRun.subagent_id}
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["run_id"] == swarmRun.subagent_id
        assert data["total"] == 1
        item = data["requests"][0]
        assert item["request_id"] == requestId
        assert item["run_id"] == swarmRun.subagent_id
        assert item["level"] == "L2"
        assert item["operation"] == "删除生产数据库表"
        assert item["status"] == "decided"
        assert item["decision"] == "approve"
        assert item["decided_by"] == "parent_agent"
        assert item["requested_at"] is not None
        assert item["decided_at"] is not None
        assert item["latency_ms"] is not None
        assert item["request_event"] is not None
        assert item["decision_event"] is not None

    @pytest.mark.asyncio
    async def test_trajectory_pending_request_shows_no_decision(
        self, swarmRun, approvals, parentMail, auditDb, auditApp
    ):
        from tests.auth_headers import overrideIdentity

        await requestRunApproval(swarmRun, "导出审计日志", level="L2")
        overrideIdentity(auditApp, MOCK_ADMIN)
        with TestClient(auditApp) as client:
            resp = client.get(
                "/api/v1/audit/approvals", params={"run_id": swarmRun.subagent_id}
            )
        assert resp.status_code == 200
        item = resp.json()["data"]["requests"][0]
        assert item["status"] == "pending"
        assert item["decision"] is None
        assert item["decision_event"] is None
        assert item["request_event"] is not None

    def test_trajectory_requires_admin(self, auditApp):
        with TestClient(auditApp, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/audit/approvals", params={"run_id": "whatever"})
        assert resp.status_code == 401, "审批审计轨迹与同域一致仅管理员可读"

    def test_trajectory_unknown_run_returns_empty(self, auditApp):
        from tests.auth_headers import overrideIdentity

        overrideIdentity(auditApp, MOCK_ADMIN)
        with TestClient(auditApp) as client:
            resp = client.get(
                "/api/v1/audit/approvals", params={"run_id": "swarm_unknown_run"}
            )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["run_id"] == "swarm_unknown_run"
        assert data["requests"] == []
        assert data["total"] == 0
