# -*- coding: utf-8 -*-
"""A1 深化：依赖门消费终态质量分级（weak/none 终态不是合格输入，须复核）。

η 门判据原本只看「completed 且验收未判不达标」——超时/取消兜底的弱终态
completion 会被当强终态放行下游。本组测试钉住：requiresReviewConfirmation
为真的前置不得自动放行依赖；strong 与历史空值（直接构造、未经迁移收口）
行为不变（向后兼容）。
"""
from unittest.mock import MagicMock, patch

import pytest

from neurova.agent.swarm import get_swarm_manager, reset_swarm_manager
from neurova.agent.swarm_support import (
    SUBAGENT_COMPLETED,
    SUBAGENT_RUNNING,
    SubAgentRun,
    transitionRun,
)


def make_mock_agent(reply="下游任务完成"):
    from unittest.mock import AsyncMock

    agent = MagicMock()
    agent.config.name = "下游Agent"
    agent.chat = AsyncMock(return_value={"text": reply})
    return agent


@pytest.fixture
def swarm():
    reset_swarm_manager()
    return get_swarm_manager()


def _upstream(swarm, sid, *, cause):
    run = SubAgentRun(subagent_id=sid, depth=1, agent_id="agent-a", agent_name="A",
                      task="前置任务", origin="chat", status="running")
    with swarm._lock:
        swarm._runs[sid] = run
    if cause is not None:
        transitionRun(run, SUBAGENT_COMPLETED, cause=cause)
    else:
        # 历史形态：直接置终态、未经 transitionRun 收口（terminal_quality 空串）
        run.status = SUBAGENT_COMPLETED
    return run


async def _spawn_downstream(swarm, dep_id):
    agent = make_mock_agent()
    with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
        return await swarm.spawn(
            task="下游任务", agent_id="researcher",
            task_unit={"goal": "下游目标", "dependencies": [dep_id]},
        )


class TestDependencyGateConsumesTerminalQuality:
    @pytest.mark.asyncio
    async def test_weak_completed_upstream_rejects_dependency(self, swarm):
        _upstream(swarm, "up-weak", cause="subagent_timeout")
        result = await _spawn_downstream(swarm, "up-weak")
        assert result.get("rejected") is True
        assert result["rejection"]["code"] == "DEPENDENCY_FAILED"

    @pytest.mark.asyncio
    async def test_strong_completed_upstream_satisfies_dependency(self, swarm):
        _upstream(swarm, "up-strong", cause="candidate_merged")
        result = await _spawn_downstream(swarm, "up-strong")
        assert result.get("rejected") is not True, result

    @pytest.mark.asyncio
    async def test_legacy_empty_quality_upstream_still_satisfies(self, swarm):
        _upstream(swarm, "up-legacy", cause=None)
        result = await _spawn_downstream(swarm, "up-legacy")
        assert result.get("rejected") is not True, result

    @pytest.mark.asyncio
    async def test_failed_upstream_still_rejected(self, swarm):
        run = SubAgentRun(subagent_id="up-fail", depth=1, agent_id="agent-a",
                          agent_name="A", task="前置任务", origin="chat", status="running")
        with swarm._lock:
            swarm._runs["up-fail"] = run
        transitionRun(run, "failed", cause="subagent_timeout")
        result = await _spawn_downstream(swarm, "up-fail")
        assert result.get("rejected") is True
        assert result["rejection"]["code"] == "DEPENDENCY_FAILED"
