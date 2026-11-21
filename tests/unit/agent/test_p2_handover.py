# -*- coding: utf-8 -*-
"""P1 移交项清偿（P2 卡）红灯测试：三件小收口。

1. MemberBatchAdd.role 持久化——FE TeamNeuacpMemberForm 已上送
   coder/reviewer/member，后端此前硬编码 "member" 丢弃入参；
2. 适配器二次 chat 会话复用——NeuacpStdioExecutor start 后再次 prompt
   曾因 NeuacpClient "already started" 失败（验收回炉轮必现）；
3. 进程池接入 spawn 装配——_resolveExternalMember 构造执行体时接
   NeuacpProcessPool（键含租户段），池故障 fail-open 退回直启。
"""
import asyncio
import sys
from pathlib import Path

import pytest

from neurova.api.endpoints import teams_api
from neurova.api.endpoints.teams_api import MemberBatchAdd, TeamCreate
from neurova.agent.neuacp.acp_client import NeuacpClient, NeuacpError
from neurova.agent.neuacp.acp_executor import NeuacpStdioExecutor
from neurova.agent.neuacp.executor import NeuacpSessionContext
from neurova.agent.neuacp.process_pool import NeuacpProcessPool
from neurova.agent.swarm import get_swarm_manager

FAKE_AGENT = Path(__file__).parent / "neuacp" / "fake_acp_agent.py"
NEUACP_TEST_DIR = FAKE_AGENT.parent


# ═══════════════════════════════════════════════════════════════════════
# 一、MemberBatchAdd 的 role 持久化（teams_api.add_members）
# ═══════════════════════════════════════════════════════════════════════

def user(uid, tenant="default", role="user"):
    return {"user_id": uid, "username": uid, "role": role, "tenant_id": tenant}


@pytest.fixture(autouse=True)
def cleanTeamsStore():
    teams_api._teams_store.clear()
    yield
    teams_api._teams_store.clear()


def makeTeam(uid="u1", tenant="t1", name="甲队"):
    return asyncio.run(teams_api.create_team(TeamCreate(name=name), user(uid, tenant)))


def memberEntry(view, uid):
    return [m for m in view.members_detail if m["user_id"] == uid][0]


def test_roleDefaultsToMemberWhenOmitted():
    """既有契约：不传 role 行为不变（缺省 member）。"""
    team = makeTeam()
    view = asyncio.run(teams_api.add_members(
        team.id, MemberBatchAdd(members=["m1"]), user("u1", "t1")))
    assert memberEntry(view, "m1")["role"] == "member"


def test_rolePersistedForRosterMember():
    """FE 上送的 role 必须落进 members_detail（原硬编码丢弃入参）。"""
    team = makeTeam()
    view = asyncio.run(teams_api.add_members(
        team.id, MemberBatchAdd(members=["m1"], prompt="负责编码", role="coder"),
        user("u1", "t1")))
    assert memberEntry(view, "m1")["role"] == "coder"
    # 落盘面（_teams_store）同步可查——不是只改了视图字段
    stored = [m for m in teams_api._teams_store[team.id]["members_detail"]
              if m["user_id"] == "m1"][0]
    assert stored["role"] == "coder"


def test_roleAcceptsReviewerAndAgentRoleValues():
    """reviewer（FE 三元之一）与既有 AgentRole 枚举值（如 author）均合法。"""
    team = makeTeam()
    view = asyncio.run(teams_api.add_members(
        team.id, MemberBatchAdd(members=["m1"], role="reviewer"), user("u1", "t1")))
    assert memberEntry(view, "m1")["role"] == "reviewer"
    view = asyncio.run(teams_api.add_members(
        team.id, MemberBatchAdd(members=["m2"], role="author"), user("u1", "t1")))
    assert memberEntry(view, "m2")["role"] == "author"


def test_roleRejectsIllegalValue():
    """非法角色 422 诚实拒绝，且不落盘。"""
    team = makeTeam()
    with pytest.raises(Exception) as exc:
        asyncio.run(teams_api.add_members(
            team.id, MemberBatchAdd(members=["m1"], role="wizard"), user("u1", "t1")))
    assert "422" in str(exc.value)
    assert teams_api._teams_store[team.id]["members_detail"] == []


# ═══════════════════════════════════════════════════════════════════════
# 二、适配器二次 chat 会话复用（NeuacpClient / NeuacpStdioExecutor）
# ═══════════════════════════════════════════════════════════════════════

def makeStdioExecutor(mode="acp_flow"):
    return NeuacpStdioExecutor(
        [sys.executable, str(FAKE_AGENT)],
        cwd=str(NEUACP_TEST_DIR),
        env_extra={"FAKE_ACP_MODE": mode},
    )


def test_clientStartIsIdempotent():
    """已启动（握手完成且进程存活）再 start：返回已存握手结果，不重复 initialize。"""
    client = NeuacpClient(
        [sys.executable, str(FAKE_AGENT)],
        cwd=str(NEUACP_TEST_DIR),
        env_extra={"FAKE_ACP_MODE": "ok"},
    )
    try:
        first = client.start()
        second = client.start()
        assert first["protocolVersion"] == "1"
        assert second == first
        assert client.is_alive
    finally:
        client.terminate()


def test_clientStartRebuildsAfterTerminate():
    """进程已死后 start：惰性重建（重新握手），不残留死态。"""
    client = NeuacpClient(
        [sys.executable, str(FAKE_AGENT)],
        cwd=str(NEUACP_TEST_DIR),
        env_extra={"FAKE_ACP_MODE": "ok"},
    )
    client.start()
    client.terminate()
    assert not client.is_alive
    handshake = client.start()
    assert handshake["protocolVersion"] == "1"
    assert client.is_alive
    client.terminate()


def test_secondChatReusesStartedProcess():
    """验收回炉轮：同一次 spawn 内二次 chat（start+prompt）不再撞 already started。"""
    async def run():
        executor = makeStdioExecutor("acp_flow")
        ctx = NeuacpSessionContext(
            member_session_id="m-1", task_text="首轮任务", cwd=str(NEUACP_TEST_DIR))
        await executor.start(ctx)
        first = await executor.prompt("首轮任务", lambda kind, text: None, None)
        await executor.start(ctx)  # 二次 chat 的 start（原：already started）
        second = await executor.prompt("回炉轮任务", lambda kind, text: None, None)
        await executor.close()
        return first, second

    first, second = asyncio.run(run())
    assert first.text == "你好 Neuacp"
    assert second.text == "你好 Neuacp"


def test_adapterSecondChatSucceeds():
    """适配器面：NeuacpMemberAdapter 连续两轮 chat 均成功（复用同一执行体进程）。"""
    from neurova.agent.neuacp import NeuacpMemberAdapter

    async def run():
        adapter = NeuacpMemberAdapter(
            makeStdioExecutor("acp_flow"), name="外部编码代理", cwd=str(NEUACP_TEST_DIR))
        first = await adapter.chat("首轮任务", stream=True, session_id="s-1", metadata={})
        second = await adapter.chat("回炉轮任务", stream=True, session_id="s-1", metadata={})
        await adapter.close()
        return first, second

    first, second = asyncio.run(run())
    assert first["text"] == "你好 Neuacp"
    assert second["text"] == "你好 Neuacp"


# ═══════════════════════════════════════════════════════════════════════
# 三、进程池接入 spawn 装配（swarm._resolveExternalMember）
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def swarm():
    return get_swarm_manager()


def patchTeams(monkeypatch, roster, tenant="t1"):
    import neurova.api.endpoints.teams_api as teamsModule

    monkeypatch.setattr(
        teamsModule, "getTeamRoster",
        lambda tid: {"id": tid, "tenant_id": tenant, "members_detail": roster},
    )


def patchInitiatorTenant(monkeypatch, tenant):
    from neurova.core import identity_context

    monkeypatch.setattr(identity_context, "get_request_user_id", lambda: "user-a")
    import neurova.auth.user_group_model as groups

    monkeypatch.setattr(groups, "resolveUserDepartment", lambda user: {"tenant_id": tenant})


def rosterWithExecutor(**overrides):
    """名册 executor 指向仓内假 ACP agent（真 stdio 子进程，离线可跑）。"""
    executor = {
        "kind": "acp", "tool": "opencode",
        "command": [sys.executable, str(FAKE_AGENT)],
        "cwd": str(NEUACP_TEST_DIR),
    }
    executor.update(overrides)
    return [{"user_id": "ext-1", "name": "外部编码代理", "role": "coder", "executor": executor}]


def injectPool(monkeypatch, pool):
    import neurova.agent.neuacp.process_pool as poolModule

    monkeypatch.setattr(poolModule, "getNeuacpProcessPool", lambda: pool)


def test_resolveAttachesPoolWithTenantKey(swarm, monkeypatch):
    """spawn 装配接池：池实例注入执行体，键含租户段（首位）+ tool/command 段。"""
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_ENABLED", "on")
    pool = NeuacpProcessPool(maxProcs=2, idleSeconds=600)
    injectPool(monkeypatch, pool)
    patchTeams(monkeypatch, rosterWithExecutor(), tenant="t1")
    patchInitiatorTenant(monkeypatch, "t1")
    try:
        adapter, error = swarm._resolveExternalMember("ext-1", "team-1")
        assert error is None
        executor = adapter._executor
        assert executor._pool is pool
        assert executor._pool_key[0] == "t1"  # 租户段在键首位（§6.4）
        assert executor._pool_key[1] == "opencode"  # tool 段
        assert executor._pool_key[2] == (sys.executable, str(FAKE_AGENT))  # command 段
        assert executor._pool_key[3] == str(NEUACP_TEST_DIR)  # cwd 段
    finally:
        pool.shutdown()


def test_pooledExecutorRunsTwoChatsAndReturnsProcessToPool(swarm, monkeypatch):
    """池化执行体全链：start 从池取件、二次 chat 复用、close 归还（不杀进程）。"""
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_ENABLED", "on")
    pool = NeuacpProcessPool(maxProcs=2, idleSeconds=600)
    injectPool(monkeypatch, pool)
    patchTeams(monkeypatch, rosterWithExecutor(), tenant="t1")
    patchInitiatorTenant(monkeypatch, "t1")
    try:
        adapter, error = swarm._resolveExternalMember("ext-1", "team-1")
        assert error is None

        async def scenario():
            first = await adapter.chat("首轮任务", stream=True, session_id="s-1", metadata={})
            second = await adapter.chat("回炉轮任务", stream=True, session_id="s-1", metadata={})
            await adapter.close()
            return first, second

        first, second = asyncio.run(scenario())
        assert "text" in first and "text" in second
        stats = pool.stats()
        assert stats["live"] == 1  # 全程只拉起一个进程（二次 chat 复用）
        assert stats["idle"] == 1  # close 归还空闲池待复用，而不是杀掉
    finally:
        pool.shutdown()


def test_poolFailureFailsOpenToDirectStart(swarm, monkeypatch):
    """池故障 fail-open：acquire 抛错时退回直启，派活不被阻断。"""
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_ENABLED", "on")

    class BrokenPool:
        def acquire(self, *args, **kwargs):
            # M10 语义切分：NeuacpError 是池的明确裁决（池满/已关闭）→ 上抛不直启；
            # 这里注入的是**设施故障**（非裁决），验证 fail-open 直启仍在。
            raise RuntimeError("池故障（测试注入）")

    pool = BrokenPool()
    injectPool(monkeypatch, pool)
    patchTeams(monkeypatch, rosterWithExecutor(), tenant="t1")
    patchInitiatorTenant(monkeypatch, "t1")
    adapter, error = swarm._resolveExternalMember("ext-1", "team-1")
    assert error is None
    assert adapter._executor._pool is pool  # 池已接入（故障在 acquire 时刻才暴露）

    async def scenario():
        return await adapter.chat("任务", stream=True, session_id="s-1", metadata={})

    result = asyncio.run(scenario())  # 不抛即 fail-open 生效
    assert "text" in result


def test_pluginExecutorNotPoolWired(swarm, monkeypatch):
    """插件执行体每任务一进程，不接池（行为保持）。"""
    from neurova.agent.neuacp import NeuacpPluginExecutor

    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_ENABLED", "on")
    pool = NeuacpProcessPool(maxProcs=2, idleSeconds=600)
    injectPool(monkeypatch, pool)
    patchTeams(monkeypatch, rosterWithExecutor(kind="plugin", tool="zcode"), tenant="t1")
    patchInitiatorTenant(monkeypatch, "t1")
    try:
        adapter, error = swarm._resolveExternalMember("ext-1", "team-1")
        assert error is None
        assert isinstance(adapter._executor, NeuacpPluginExecutor)
        assert getattr(adapter._executor, "_pool", None) is None
    finally:
        pool.shutdown()
