"""
SwarmManager 蜂群编排单元测试

覆盖：
- spawn 前台/后台模式
- Agent 实例解析与回退（请求 id 不存在 → default）
- 双通道回流：报告直传 + 上下文池归档
- SUBAGENT_STARTED / CHUNK / COMPLETED 事件广播
- 故障隔离（子 Agent 异常 → failed 结果不抛出）
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.swarm import SwarmManager, get_swarm_manager, reset_swarm_manager


def make_mock_agent(name="子Agent", reply="任务完成报告"):
    agent = MagicMock()
    agent.config.name = name
    agent.chat = AsyncMock(return_value={"text": reply})
    return agent


def make_initiator():
    """带上下文池的发起者 Agent mock"""
    initiator = MagicMock()
    initiator.context_pool.add_context = MagicMock()
    return initiator


@pytest.fixture
def swarm():
    reset_swarm_manager()
    return get_swarm_manager()


class TestSpawnForeground:
    """前台派生"""

    @pytest.mark.asyncio
    async def test_spawn_success_returns_report(self, swarm):
        agent = make_mock_agent(reply="调研完成：结论XYZ")
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="调研某主题", agent_id="researcher")

        assert result["status"] == "completed"
        assert result["report"] == "调研完成：结论XYZ"
        assert result["agent_id"] == "researcher"
        assert result["subagent_id"].startswith("swarm_")
        # chat 被调用，metadata 携带蜂群标记
        _, kwargs = agent.chat.call_args
        assert kwargs["metadata"]["source"] == "swarm"
        assert kwargs["metadata"]["subagent_id"] == result["subagent_id"]

    @pytest.mark.asyncio
    async def test_fallback_to_default_when_agent_missing(self, swarm):
        default_agent = make_mock_agent(name="默认Agent")

        def resolve(agent_id):
            return default_agent if agent_id == "default" else None

        with patch("neurova.api.endpoints.get_agent_instance", side_effect=resolve):
            result = await swarm.spawn(task="任务", agent_id="ghost")

        assert result["status"] == "completed"
        assert result["agent_id"] == "default"

    @pytest.mark.asyncio
    async def test_no_agent_available_returns_error(self, swarm):
        with patch("neurova.api.endpoints.get_agent_instance", return_value=None), patch(
            "neurova.api.endpoints.get_app_state", return_value={"agents": {}}
        ):
            result = await swarm.spawn(task="任务")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_empty_task_rejected(self, swarm):
        result = await swarm.spawn(task="  ")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_subagent_failure_isolated(self, swarm):
        agent = make_mock_agent()
        agent.chat = AsyncMock(side_effect=RuntimeError("LLM 超时"))
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="任务")

        assert result["status"] == "failed"
        assert "LLM 超时" in result["error"]


class TestBackgroundSpawn:
    """后台派生"""

    @pytest.mark.asyncio
    async def test_background_returns_immediately(self, swarm):
        agent = make_mock_agent()

        async def slow_chat(*args, **kwargs):
            await asyncio.sleep(0.05)
            return {"text": "后台完成"}

        agent.chat = AsyncMock(side_effect=slow_chat)
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="长任务", background=True)

        assert result["background"] is True
        assert result["status"] == "pending"

        # 等待后台任务完成后可查询
        await asyncio.sleep(0.15)
        status = swarm.status(result["subagent_id"])
        assert status["status"] == "completed"
        assert status["report"] == "后台完成"

    @pytest.mark.asyncio
    async def test_status_unknown_id(self, swarm):
        assert "error" in swarm.status("swarm_nonexistent")


class TestEventBroadcast:
    """SUBAGENT_* 事件广播"""

    @pytest.mark.asyncio
    async def test_started_and_completed_broadcast(self, swarm):
        agent = make_mock_agent()
        broadcasts = []

        class FakeMgr:
            def register_or_create_session(self, session_id, user_id, **kwargs):
                return MagicMock()

            async def broadcast_event(self, session_id, event):
                broadcasts.append((session_id, event.event_type.value, event.payload))

        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent), patch(
            "neurova.sync.session_sync_manager.get_session_sync_manager", return_value=FakeMgr()
        ):
            await swarm.spawn(task="任务", session_id="sess-1", initiator_agent=None)

        types = [t for _, t, _ in broadcasts]
        assert "subagent_started" in types
        assert "subagent_completed" in types
        assert all(sid == "sess-1" for sid, _, _ in broadcasts)
        completed_payload = next(p for _, t, p in broadcasts if t == "subagent_completed")
        assert completed_payload["report"] == "任务完成报告"

    @pytest.mark.asyncio
    async def test_no_session_skips_broadcast(self, swarm):
        agent = make_mock_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent), patch(
            "neurova.sync.session_sync_manager.get_session_sync_manager"
        ) as mock_mgr:
            await swarm.spawn(task="任务", session_id=None)
        mock_mgr.assert_not_called()


class TestPoolArchive:
    """双通道之池归档"""

    @pytest.mark.asyncio
    async def test_report_archived_to_initiator_pool(self, swarm):
        agent = make_mock_agent(name="研究员", reply="关键发现：结论A")
        initiator = make_initiator()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            await swarm.spawn(task="分析数据", initiator_agent=initiator)

        initiator.context_pool.add_context.assert_called_once()
        ctx_input = initiator.context_pool.add_context.call_args.args[0]
        assert ctx_input.source.value == "experience"
        assert "[子Agent报告]" in ctx_input.content
        assert "研究员" in ctx_input.content
        assert "结论A" in ctx_input.content

    @pytest.mark.asyncio
    async def test_failed_run_not_archived(self, swarm):
        agent = make_mock_agent()
        agent.chat = AsyncMock(side_effect=RuntimeError("boom"))
        initiator = make_initiator()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            await swarm.spawn(task="任务", initiator_agent=initiator)

        initiator.context_pool.add_context.assert_not_called()


class TestSingleton:
    def test_get_swarm_manager_singleton(self):
        reset_swarm_manager()
        m1 = get_swarm_manager()
        m2 = get_swarm_manager()
        assert m1 is m2
        reset_swarm_manager()
