# -*- coding: utf-8 -*-
"""子代理深度上限（Issue #268 切片 D）——「深度是契约，不是广度的副作用」。

根因（方案 §2 缺陷修正后的那条）：蜂群派生的**深度**今天没有任何声明——
`MAX_ACTIVE_CHILDREN=5` 是**全局广度**硬限（`_count_active()` 数的是全部
pending/running，与层级无关），而 member 是一个完整 Agent、手里也有
`spawn_subagent` 工具，于是它可以再派生。深度因此只是「全局广度帽跑满之前
先撞上」的**偶发现象**，不是被任何配置键或常量声明过的契约：

- 广度为 5 时，单链最多嵌 5 层（还是 4？取决于兄弟占用）——**由兄弟数量决定**；
- 兄弟全是后台长任务时，一条链在第 1 层就被拒，另一条能嵌到 5 层——同一天花板
  读出两个深度，二者都不是「声明」的；
- 没有任何配置键能表达「这个部署最多允许嵌几层」。

本片把深度变成**可声明的契约**：一条单源配置键 `max_subagent_depth`，
`spawn()` 在派生**之前**用「发起者所在深度 + 1」与之比较，超限走既有
`_rejection` 结构化拒绝（决策非故障，`is_policy_denial` 归类不变）。

判据（每条都要求「改前实测不成立、改后成立」）：
1. 存在声明的深度常量与单源配置键（符号级静态判据）；
2. `spawn()` 的返回值在超深时是 `swarm_rejection` 且 `code=SUBAGENT_DEPTH_EXCEEDED`
   ——活体：真人造嵌套链，第 N 层被拒；
3. 深度不随兄弟数量改变——同一条链的封顶层数在「0 个兄弟」与「若干兄弟」两种
   场景下**逐项相等**（这正是广度副作用与声明契约的分界）；
4. 广度闸仍然独立生效（深度闸不得把广度闸顶替掉）。

替身只放在模型边界（子 Agent 的 `chat`）与 Agent 解析边界
（`get_agent_instance`）；深度记账、拒绝、配额闭环全部走生产代码。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from neurova.agent.swarm import SwarmManager, get_swarm_manager, reset_swarm_manager

SWARM_PY = Path(__file__).resolve().parents[3] / "neurova" / "agent" / "swarm.py"
LIMITS_PY = (
    Path(__file__).resolve().parents[3]
    / "neurova" / "security" / "agent_limits_settings.py"
)


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture
def swarm():
    reset_swarm_manager()
    return get_swarm_manager()


def _make_mock_agent(name="子Agent", reply="任务完成报告"):
    agent = MagicMock()
    agent.config.name = name
    agent.chat = AsyncMock(return_value={"text": reply})
    return agent


class TestDepthIsDeclaredNotIncidental:
    """第 1 条：深度必须是**声明**的（常量 + 单源配置键），不是广度的残留。"""

    def test_swarmDeclaresMaxDepthConstant(self):
        """`SwarmManager` 必须有显式的深度常量（广度常量之外的第二条契约）。"""
        assert hasattr(SwarmManager, "MAX_SUBAGENT_DEPTH"), (
            "SwarmManager 缺 MAX_SUBAGENT_DEPTH——深度只由 MAX_ACTIVE_CHILDREN "
            "（广度）间接封顶，即『深度是广度的副作用』"
        )
        assert isinstance(SwarmManager.MAX_SUBAGENT_DEPTH, int)
        assert SwarmManager.MAX_SUBAGENT_DEPTH >= 0

    def test_maxDepthHasSingleSourceConfigKey(self):
        """深度上限有**单源**配置键：`agent_limits_settings.DEFAULTS` 里一处定义。"""
        from neurova.security import agent_limits_settings as limits

        assert "max_subagent_depth" in limits.DEFAULTS, (
            "深度上限没有配置键——它今天不受任何配置管辖（如 GoalGate 的 15 硬顶）"
        )
        # 合法域常量同源（夹紧用），不是第二份尺度
        assert hasattr(limits, "MIN_SUBAGENT_DEPTH")
        assert hasattr(limits, "MAX_SUBAGENT_DEPTH_LIMIT")

    def test_effectiveLimitsCarryDepth(self):
        """`get_effective_limits()` 必须把深度键夹紧后带出（与其余键同口径）。"""
        from neurova.security import agent_limits_settings as limits

        eff = limits.get_effective_limits()
        assert "max_subagent_depth" in eff, "生效限制里没有深度键——配置只写不读"
        low, high = eff["max_subagent_depth"], limits.MAX_SUBAGENT_DEPTH_LIMIT
        assert 0 <= low <= high


class TestDepthRejectsBeforeDispatch:
    """第 2 条：超深在**派生之前**被结构化拒绝。"""

    @pytest.mark.asyncio
    async def test_overDeepSpawnIsRejected(self, swarm):
        """伪造「已在第 N 层」的上下文：第 N+1 次派生必须被深度闸拒绝。"""
        depth_mod = pytest.importorskip("neurova.agent.swarm")
        assert hasattr(depth_mod, "set_subagent_depth"), (
            "没有深度上下文的写入点——深度无从随派生链传递"
        )

        limit = SwarmManager.MAX_SUBAGENT_DEPTH
        agent = _make_mock_agent()
        token = depth_mod.set_subagent_depth(limit)
        try:
            with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
                result = await swarm.spawn(task="越深任务")
        finally:
            depth_mod.reset_subagent_depth(token)

        assert result.get("rejected") is True, "超深派生必须被数据层结构化拒绝"
        assert result["rejection"]["code"] == "SUBAGENT_DEPTH_EXCEEDED"
        assert result["rejection"]["message"]
        # 拒绝是决策不是故障（既有口径）
        from neurova.security.governance import is_policy_denial

        assert is_policy_denial(result) is True
        agent.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_withinDepthSpawnSucceeds(self, swarm):
        """第 1 层（发起者深度 0 → 子深度 1）在合法域内必须放行。"""
        agent = _make_mock_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="正常任务")
        assert result.get("rejected") is not True
        assert result["status"] == "completed"


class TestDepthIndependentOfBreadth:
    """第 3 条：封顶层数不随兄弟数量改变——广度副作用 vs 声明契约的分界。"""

    @pytest.mark.asyncio
    async def test_depthCeilingIndependentOfSiblingCount(self):
        """「链根」派生的**同一条链**，其封顶深度在兄弟数 0 与 3 两种场景下逐项相等。

        递归由替身 `chat` 在子 Agent 内**再调一次 `swarm.spawn`** 模拟
        （member 是一个完整 Agent、手里有 spawn_subagent 工具，这是真实形态）。
        只统计**任务文本以「链根」开头**的那条链（兄弟链各算各的，不混入）。
        member 的实际深度由生产侧 `current_subagent_depth()` 读出——不用测试自行推算。
        """
        limit = SwarmManager.MAX_SUBAGENT_DEPTH
        depth_mod = pytest.importorskip("neurova.agent.swarm")

        async def _measure(sibling_count: int):
            reset_swarm_manager()
            local = get_swarm_manager()
            chain_depths = []

            async def nested_chat(task, **kwargs):
                if task.startswith("链根"):
                    chain_depths.append(depth_mod.current_subagent_depth())
                    # member 内再派生一层——真实形态：member 手里有 spawn_subagent
                    await local.spawn(task=f"{task}>子", background=False)
                return {"text": "报表"}

            agent = MagicMock()
            agent.config.name = "链式Agent"
            agent.chat = AsyncMock(side_effect=nested_chat)

            with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
                siblings = [
                    asyncio.ensure_future(local.spawn(task=f"兄弟{i}", background=False))
                    for i in range(sibling_count)
                ]
                await local.spawn(task="链根", background=False)
                if siblings:
                    await asyncio.gather(*siblings, return_exceptions=True)
            return chain_depths

        no_sibling = await _measure(0)
        with_sibling = await _measure(3)
        # 执行过的链根 member 深度序列：应为 1..limit（第 limit+1 层被拒，不执行 chat）
        assert no_sibling == list(range(1, limit + 1)), (
            f"无兄弟时链上深度序列 {no_sibling} != 1..{limit}"
        )
        assert with_sibling == no_sibling, (
            f"有兄弟时链上深度序列 {with_sibling} != 无兄弟时 {no_sibling}——"
            "深度仍被广度推挤（广度副作用）"
        )


class TestDepthKeyIsWiredNotWriteOnly:
    """配置键不是「只写不读」：台账登记 + 真读取点（协作红线：不留断点）。"""

    def test_depthKeyRegisteredInDeadlineLedger(self):
        """`max_subagent_depth` 必须进 toolLoopDeadlines 台账（与同族键同待遇）。"""
        ledger = (
            Path(__file__).resolve().parents[3]
            / "scripts" / "ci" / "toolLoopDeadlines.txt"
        ).read_text(encoding="utf-8")
        rows = [ln for ln in ledger.splitlines()
                if ln.startswith("max_subagent_depth |")]
        assert len(rows) == 1, "深度键未登记或登记重复（第二份台账即是第二份事实源）"
        assert "consumed" in rows[0], "深度键的消费点没被机器算成可达"

    def test_depthGateReadsSingleSource(self):
        """深度闸的生效值来自单源配置：改配置读数随之变（不是常量硬顶）。"""
        from neurova.security import agent_limits_settings as limits

        swarm = get_swarm_manager()
        original = limits.DEFAULTS["max_subagent_depth"]
        try:
            limits.DEFAULTS["max_subagent_depth"] = 0
            assert swarm._effective_max_depth() == 0, (
                "生效深度不随配置变——说明它读的是常量（第二份尺度）"
            )
            limits.DEFAULTS["max_subagent_depth"] = original
            assert swarm._effective_max_depth() == original
        finally:
            limits.DEFAULTS["max_subagent_depth"] = original


class TestBreadthGateRemainsIndependent:
    """第 4 条：深度闸不得顶替广度闸。"""

    @pytest.mark.asyncio
    async def test_breadthCapStillRejects(self, swarm):
        """广度超限仍走 MAX_ACTIVE_CHILDREN（深度封顶不等于放宽广度）。"""
        agent = _make_mock_agent()

        async def slow_chat(*a, **k):
            await asyncio.sleep(30)
            return {"text": "x"}

        agent.chat = AsyncMock(side_effect=slow_chat)
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            tasks = [
                swarm.spawn(task=f"t{i}", background=True)
                for i in range(SwarmManager.MAX_ACTIVE_CHILDREN)
            ]
            await asyncio.gather(*tasks)
            overflow = await swarm.spawn(task="超限任务")
        assert overflow.get("rejected") is True
        assert overflow["rejection"]["code"] == "MAX_ACTIVE_CHILDREN"

