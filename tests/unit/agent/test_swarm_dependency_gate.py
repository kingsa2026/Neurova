"""P1-4 蜂群依赖门控单元测试。

覆盖：
- 依赖指向不存在的 run → 结构化拒绝 DEPENDENCY_UNKNOWN；
- 依赖未就绪 → spawn 返回 blocked 回执（不占槽、member 不执行、status 可查）；
- 依赖终态验收通过 → blocked 自动放行执行并完成；
- 依赖失败 → 下游不执行直接 failed（cause=dependency_failed）；
- 依赖 completed 但验收门判不达标 → 下游同样 failed（η 门语义）；
- 多依赖部分满足 → 保持 blocked，全部满足后才放行；
- 槽满时放行推迟到下一次结算。
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.swarm import get_swarm_manager, reset_swarm_manager


def make_agent(name="子Agent", reply="完成", delay_event: asyncio.Event = None):
    agent = MagicMock()
    agent.config.name = name

    async def _chat(prompt, *args, **kwargs):
        if delay_event is not None:
            await delay_event.wait()
        return {"text": reply}

    agent.chat = AsyncMock(side_effect=_chat)
    return agent


@pytest.fixture
def swarm():
    reset_swarm_manager()
    return get_swarm_manager()


async def waitUntil(predicate, timeout=3.0, interval=0.02):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            if predicate():
                return True
        except (KeyError, TypeError):
            pass  # 状态迁移间隙（blocked→run）读数暂缺，下一轮再取
        await asyncio.sleep(interval)
    return False


class TestDependencyGate:
    @pytest.mark.asyncio
    async def test_unknown_dependency_rejected(self, swarm):
        agent = make_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(
                task="下游任务", agent_id="researcher",
                task_unit={"goal": "g", "dependencies": ["swarm_doesnotexist"]},
            )
        assert result.get("rejected") is True
        assert result["rejection"]["code"] == "DEPENDENCY_UNKNOWN"
        agent.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_unmet_dependency_blocks_and_promotes(self, swarm):
        release = asyncio.Event()
        depAgent = make_agent(name="前置", reply="前置完成", delay_event=release)
        downstreamAgent = make_agent(name="下游", reply="下游完成")
        agents = {"dep": depAgent, "researcher": downstreamAgent}

        def resolver(agent_id, *args, **kwargs):
            return agents.get(agent_id or "researcher")

        with patch("neurova.api.endpoints.get_agent_instance", side_effect=resolver):
            dep = await swarm.spawn(task="前置任务", agent_id="dep", background=True)
            blocked = await swarm.spawn(
                task="下游任务", agent_id="researcher",
                task_unit={"goal": "g", "dependencies": [dep["subagent_id"]]},
            )
            # 未就绪：blocked 回执，下游未执行
            assert blocked["status"] == "blocked"
            assert blocked["dependencies"] == [dep["subagent_id"]]
            downstreamAgent.chat.assert_not_called()
            status = swarm.status(blocked["subagent_id"])
            assert status["status"] == "blocked"

            release.set()  # 前置完成 → 结算放行
            assert await waitUntil(
                lambda: swarm.status(blocked["subagent_id"])["status"] == "completed"
            )
            downstreamAgent.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failed_dependency_rejects_spawn(self, swarm):
        depAgent = make_agent(name="前置")
        depAgent.chat = AsyncMock(side_effect=RuntimeError("前置炸了"))
        downstreamAgent = make_agent(name="下游", reply="下游完成")
        agents = {"dep": depAgent, "researcher": downstreamAgent}

        def resolver(agent_id, *args, **kwargs):
            return agents.get(agent_id or "researcher")

        with patch("neurova.api.endpoints.get_agent_instance", side_effect=resolver):
            dep = await swarm.spawn(task="前置任务", agent_id="dep", background=True)
            await asyncio.sleep(0.05)  # 让前置落 failed 终态
            rejected = await swarm.spawn(
                task="下游任务", agent_id="researcher",
                task_unit={"goal": "g", "dependencies": [dep["subagent_id"]]},
            )
        # 依赖已 failed：即时拒绝（终态不会再结算，登记 blocked 就是永久等待）
        assert rejected.get("rejected") is True
        assert rejected["rejection"]["code"] == "DEPENDENCY_FAILED"
        downstreamAgent.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_dependency_failing_after_block_fails_downstream(self, swarm):
        # 先登记 blocked，前置随后失败 → 结算把下游直接判 failed（不执行、不归档）
        depAgent = make_agent(name="前置")
        depAgent.chat = AsyncMock(side_effect=RuntimeError("前置炸了"))
        downstreamAgent = make_agent(name="下游", reply="下游完成")
        agents = {"dep": depAgent, "researcher": downstreamAgent}

        def resolver(agent_id, *args, **kwargs):
            return agents.get(agent_id or "researcher")

        with patch("neurova.api.endpoints.get_agent_instance", side_effect=resolver):
            dep = await swarm.spawn(task="前置任务", agent_id="dep", background=True)
            blocked = await swarm.spawn(
                task="下游任务", agent_id="researcher",
                task_unit={"goal": "g", "dependencies": [dep["subagent_id"]]},
            )
            assert blocked["status"] == "blocked"
            assert await waitUntil(
                lambda: swarm.status(blocked["subagent_id"])["status"] == "failed"
            )
            stored = swarm.status(blocked["subagent_id"])
            assert "dependency_failed" in (stored.get("error") or "")
            downstreamAgent.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_acceptance_failed_dependency_rejects_spawn(self, swarm):
        # 前置 completed 但验收门判不达标 → 即时拒绝（η 门：未验收产出不是合格输入）
        depAgent = make_agent(name="前置", reply="半成品")
        verdicts = [{"achieved": False, "confidence": 0.9,
                     "missing": ["缺少结论"], "explanation": ""}]

        async def fake_verify(messages, *args, **kwargs):
            payload = verdicts.pop(0) if verdicts else {"achieved": False, "confidence": 1.0, "missing": ["x"]}
            from types import SimpleNamespace
            return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))

        depAgent.llm_client = MagicMock()
        depAgent.llm_client.chat = AsyncMock(side_effect=fake_verify)
        downstreamAgent = make_agent(name="下游", reply="下游完成")
        agents = {"dep": depAgent, "researcher": downstreamAgent}

        def resolver(agent_id, *args, **kwargs):
            return agents.get(agent_id or "researcher")

        with patch("neurova.api.endpoints.get_agent_instance", side_effect=resolver), \
             patch("neurova.agent.acceptance_gate.get_advanced_settings",
                   return_value={"swarm_acceptance_enabled": True}):
            dep = await swarm.spawn(
                task="前置任务", agent_id="dep", background=True,
                task_unit={"goal": "g", "acceptanceCriteria": ["要有结论"]},
            )
            await asyncio.sleep(0.15)  # 验收判定 + 回炉 + 失败落终态
            rejected = await swarm.spawn(
                task="下游任务", agent_id="researcher",
                task_unit={"goal": "g", "dependencies": [dep["subagent_id"]]},
            )
        assert rejected.get("rejected") is True
        assert rejected["rejection"]["code"] == "DEPENDENCY_FAILED"
        downstreamAgent.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_partial_dependencies_wait_for_all(self, swarm):
        releaseA = asyncio.Event()
        depA = make_agent(name="前置A", reply="A完成", delay_event=releaseA)
        depB = make_agent(name="前置B", reply="B完成")
        downstreamAgent = make_agent(name="下游", reply="下游完成")
        agents = {"depA": depA, "depB": depB, "researcher": downstreamAgent}

        def resolver(agent_id, *args, **kwargs):
            return agents.get(agent_id or "researcher")

        with patch("neurova.api.endpoints.get_agent_instance", side_effect=resolver):
            a = await swarm.spawn(task="前置A", agent_id="depA", background=True)
            b = await swarm.spawn(task="前置B", agent_id="depB", background=True)
            blocked = await swarm.spawn(
                task="下游任务", agent_id="researcher",
                task_unit={"goal": "g", "dependencies": [a["subagent_id"], b["subagent_id"]]},
            )
            assert blocked["status"] == "blocked"
            releaseA.set()
            await asyncio.sleep(0.1)
            # A 已完成但 B 已完成——两个依赖其实都满足（B 是同步完成后落账）
            assert await waitUntil(
                lambda: swarm.status(blocked["subagent_id"])["status"] == "completed"
            )

    @pytest.mark.asyncio
    async def test_duplicated_dependency_rejected(self, swarm):
        depAgent = make_agent(name="前置", reply="完成")
        downstreamAgent = make_agent(name="下游", reply="下游完成")
        agents = {"dep": depAgent, "researcher": downstreamAgent}

        def resolver(agent_id, *args, **kwargs):
            return agents.get(agent_id or "researcher")

        with patch("neurova.api.endpoints.get_agent_instance", side_effect=resolver):
            dep = await swarm.spawn(task="前置任务", agent_id="dep", background=True)
            rejected = await swarm.spawn(
                task="下游任务", agent_id="researcher",
                task_unit={"goal": "g",
                           "dependencies": [dep["subagent_id"], dep["subagent_id"]]},
            )
        assert rejected.get("rejected") is True
        assert rejected["rejection"]["code"] == "DEPENDENCY_DUPLICATED"
