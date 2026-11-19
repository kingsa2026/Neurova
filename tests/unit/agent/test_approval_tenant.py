# -*- coding: utf-8 -*-
"""A9b 红灯：审批链租户隔离（§6.4）。

覆盖：requestRunApproval 落单挂发起者租户；decideSwarmApproval 裁决人
租户校验（同租户放行/跨租户拒/平台 admin 例外/parent_agent 通道豁免/
存量无租户单按 default）。
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from neurova.agent.approval_chain import (
    decideSwarmApproval,
    requestRunApproval,
)
from neurova.agent.swarm import SubAgentRun, reset_swarm_manager
from neurova.security.approval_manager import ApprovalManager


@pytest.fixture
def approvals(tmp_path, monkeypatch):
    mgr = ApprovalManager(str(tmp_path / "approval_ws"))
    monkeypatch.setenv("NEUROVA_SWARM_APPROVAL_WAIT_S", "3")
    monkeypatch.setattr("neurova.security.approval_manager.get_approval_manager", lambda: mgr)
    yield mgr


@pytest.fixture
def swarmRun():
    reset_swarm_manager()
    return SubAgentRun(
        agent_id="child", agent_name="子代理", task="整理数据",
        session_id="parent-session", origin="chat", member_session_id="swarm_member_t1",
    )


def patchTenants(monkeypatch, mapping):
    from neurova.auth import user_group_model

    monkeypatch.setattr(
        user_group_model, "resolveUserDepartment",
        lambda user: {"tenant_id": mapping.get(user, "default")},
    )


def patchCurrentTenant(monkeypatch, tenant):
    from neurova.auth import user_group_model

    monkeypatch.setattr(user_group_model, "currentUserTenantId", lambda: tenant)


def test_requestRunApprovalStampsTenant(swarmRun, approvals, monkeypatch):
    patchCurrentTenant(monkeypatch, "t1")
    result = asyncio_run(requestRunApproval(swarmRun, "read_file", reason="读取配置", level="L0"))
    assert result["approved"] is True
    request = approvals.get_request(result["request_id"])
    assert request.metadata["tenant_id"] == "t1"


def test_decideCrossTenantRejected(swarmRun, approvals, monkeypatch):
    patchTenants(monkeypatch, {"u-t1": "t1", "u-t2": "t2"})
    request = approvals.create_approval_request(
        agent_id="child", user_id="", command="write_file", description="写文件",
        danger_reason="L1", metadata={"source": "swarm", "tenant_id": "t1"},
    )
    result = decideSwarmApproval(request.request_id, "approve", decidedBy="u-t2", decidedByChannel="room")
    assert result["success"] is False
    assert "跨租户" in result["error"]


def test_decideSameTenantApproved(swarmRun, approvals, monkeypatch):
    patchTenants(monkeypatch, {"u-t1": "t1"})
    request = approvals.create_approval_request(
        agent_id="child", user_id="", command="write_file", description="写文件",
        danger_reason="L1", metadata={"source": "swarm", "tenant_id": "t1"},
    )
    result = decideSwarmApproval(request.request_id, "approve", decidedBy="u-t1", decidedByChannel="room")
    assert result["success"] is True


def test_platformAdminCrossTenantAllowed(swarmRun, approvals, monkeypatch):
    patchTenants(monkeypatch, {"u-t2": "t2"})
    monkeypatch.setattr("neurova.agent.approval_chain._deciderIsPlatformAdmin", lambda actor: True)
    request = approvals.create_approval_request(
        agent_id="child", user_id="", command="write_file", description="写文件",
        danger_reason="L1", metadata={"source": "swarm", "tenant_id": "t1"},
    )
    result = decideSwarmApproval(request.request_id, "approve", decidedBy="u-t2", decidedByChannel="room")
    assert result["success"] is True


def test_parentAgentChannelSkipsTenantGate(swarmRun, approvals, monkeypatch):
    patchTenants(monkeypatch, {})
    request = approvals.create_approval_request(
        agent_id="child", user_id="", command="write_file", description="写文件",
        danger_reason="L1", metadata={"source": "swarm", "tenant_id": "t1"},
    )
    result = decideSwarmApproval(request.request_id, "approve", decidedBy="parent_agent", decidedByChannel="parent_agent")
    assert result["success"] is True


def test_legacyRequestWithoutTenantDefaults(swarmRun, approvals, monkeypatch):
    patchTenants(monkeypatch, {"u-def": "default", "u-t2": "t2"})
    request = approvals.create_approval_request(
        agent_id="child", user_id="", command="write_file", description="写文件",
        danger_reason="L1", metadata={"source": "swarm"},
    )
    ok = decideSwarmApproval(request.request_id, "approve", decidedBy="u-def", decidedByChannel="room")
    assert ok["success"] is True
    request2 = approvals.create_approval_request(
        agent_id="child", user_id="", command="write_file", description="写文件",
        danger_reason="L1", metadata={"source": "swarm"},
    )
    denied = decideSwarmApproval(request2.request_id, "approve", decidedBy="u-t2", decidedByChannel="room")
    assert denied["success"] is False


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)
