# -*- coding: utf-8 -*-
"""A4 红灯：swarm 外部成员解析（_resolveExternalMember）契约测试。

覆盖：名册 executor 成员 → NeuacpMemberAdapter；开关 off 诚实拒绝；
跨租户派活拒绝（§6.4）；无 executor 成员回退内置；缺启动命令拒绝；
plugin 形态在执行体就绪前拒绝。
"""
import pytest

from neurova.agent.swarm import get_swarm_manager


@pytest.fixture
def swarm():
    return get_swarm_manager()


def patchTeams(monkeypatch, roster, team=None):
    """getTeamRoster 真实契约：返回团队 dict 浅拷贝（含 members_detail/tenant_id）。"""
    import neurova.api.endpoints.teams_api as teams_api

    tenant = (team or {}).get("tenant_id", "default")
    monkeypatch.setattr(
        teams_api, "getTeamRoster",
        lambda tid: {"id": tid, "tenant_id": tenant, "members_detail": roster},
    )


def patchInitiatorTenant(monkeypatch, tenant):
    from neurova.core import identity_context

    monkeypatch.setattr(identity_context, "get_request_user_id", lambda: "user-a")
    import neurova.auth.user_group_model as groups

    monkeypatch.setattr(groups, "resolveUserDepartment", lambda user: {"tenant_id": tenant})


def rosterWithExecutor(**executorOverrides):
    executor = {"kind": "acp", "tool": "opencode", "command": ["echo", "acp"], "cwd": "."}
    executor.update(executorOverrides)
    return [{"user_id": "ext-1", "name": "外部编码代理", "role": "coder", "executor": executor}]


def test_externalMemberResolvesToAdapter(swarm, monkeypatch):
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_ENABLED", "on")
    patchTeams(monkeypatch, rosterWithExecutor())
    patchInitiatorTenant(monkeypatch, "default")
    adapter, error = swarm._resolveExternalMember("ext-1", "team-1")
    assert error is None
    assert adapter is not None
    assert adapter.config.name == "外部编码代理"
    assert adapter.current_session_id is None


def test_disabledSwitchRejectsHonestly(swarm, monkeypatch):
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_ENABLED", "off")
    patchTeams(monkeypatch, rosterWithExecutor())
    adapter, error = swarm._resolveExternalMember("ext-1", "team-1")
    assert adapter is None
    assert error and "未启用" in error


def test_crossTenantDispatchRejected(swarm, monkeypatch):
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_ENABLED", "on")
    patchTeams(monkeypatch, rosterWithExecutor(), team={"id": "team-1", "tenant_id": "t1"})
    patchInitiatorTenant(monkeypatch, "t2")
    adapter, error = swarm._resolveExternalMember("ext-1", "team-1")
    assert adapter is None
    assert error and "跨租户" in error


def test_sameTenantAllowed(swarm, monkeypatch):
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_ENABLED", "on")
    patchTeams(monkeypatch, rosterWithExecutor(), team={"id": "team-1", "tenant_id": "t1"})
    patchInitiatorTenant(monkeypatch, "t1")
    adapter, error = swarm._resolveExternalMember("ext-1", "team-1")
    assert error is None
    assert adapter is not None


def test_memberWithoutExecutorFallsBack(swarm, monkeypatch):
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_ENABLED", "on")
    patchTeams(monkeypatch, [{"user_id": "ext-1", "name": "内置成员"}])
    adapter, error = swarm._resolveExternalMember("ext-1", "team-1")
    assert adapter is None and error is None


def test_unknownAgentFallsBack(swarm, monkeypatch):
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_ENABLED", "on")
    patchTeams(monkeypatch, [])
    adapter, error = swarm._resolveExternalMember("ext-1", "team-1")
    assert adapter is None and error is None


def test_missingCommandRejected(swarm, monkeypatch):
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_ENABLED", "on")
    patchTeams(monkeypatch, rosterWithExecutor(command=[]))
    adapter, error = swarm._resolveExternalMember("ext-1", "team-1")
    assert adapter is None
    assert error and "启动命令" in error


def test_pluginKindRejectedUntilExecutorAvailable(swarm, monkeypatch):
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_ENABLED", "on")
    patchTeams(monkeypatch, rosterWithExecutor(kind="plugin", tool="zcode"))
    adapter, error = swarm._resolveExternalMember("ext-1", "team-1")
    assert adapter is None
    assert error and "插件" in error


def test_spawnRejectsWhenExternalUnavailable(swarm, monkeypatch):
    """spawn 集成：开关 off 时对 executor 成员派活返回结构化拒绝（不建 run）。"""
    import asyncio

    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_ENABLED", "off")
    patchTeams(monkeypatch, rosterWithExecutor())
    before = len(swarm._runs)
    result = asyncio.run(swarm.spawn("做个任务", agent_id="ext-1", session_id=None, team_id="team-1"))
    assert result.get("rejected") is True
    rejection = result.get("rejection") or {}
    assert rejection.get("code") == "EXTERNAL_AGENT_UNAVAILABLE"
    assert "未启用" in str(rejection.get("message", ""))
    assert len(swarm._runs) == before
