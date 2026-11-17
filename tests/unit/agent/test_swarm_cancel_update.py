# -*- coding: utf-8 -*-
"""H 批补差：父侧叫停（cancel_subagent）与运行中改需求（continue_subagent 放宽）。

对照 deepagents 异步子代理五工具的两个缺口：
- 叫停：cancelRun 对运行中 run 取消其 asyncio 任务（CancelledError 路径既有
  落账/释放槽位/部分报告交接应照常工作）；对 blocked 等待件直接判失败落账
  （不再因依赖结算而启动）；对已终态/未知 id 幂等失败。
- 改需求：continue_subagent 放宽到运行中 run——mode=steer 把新指令注入成员
  会话插话队列（下一工具轮生效，尽力而为）；mode=restart 先叫停再按终态
  续跑链重派（resumed_from 溯源保留）。
- 工具面：cancel_subagent 注册 schema；子代理白名单剔除（成员不得叫停兄弟/
  自己的运行）。
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from neurova.agent.swarm import (
    SUBAGENT_CAUSE_CANCELLED,
    SUBAGENT_RUNNING,
    computeSubagentToolAllowlist,
    get_swarm_manager,
    reset_swarm_manager,
)
from neurova.agent.swarm_event_log import readRunEvents
from neurova.core.steer_queue import get_steer_queue


def make_slow_agent(seconds=0.5, reply="慢慢做完"):
    class SlowAgent:
        def __init__(self):
            self.config = MagicMock()
            self.config.name = "慢子Agent"

        async def chat(self, task, **kwargs):
            await asyncio.sleep(seconds)
            return {"text": reply}

    return SlowAgent()


def make_quick_agent(reply="重派后完成"):
    class QuickAgent:
        def __init__(self):
            self.config = MagicMock()
            self.config.name = "快子Agent"

        async def chat(self, task, **kwargs):
            return {"text": reply}

    return QuickAgent()


@pytest.fixture
def swarm():
    reset_swarm_manager()
    yield get_swarm_manager()
    reset_swarm_manager()


async def _waitForTerminal(swarm, subagentId, seconds=3.0):
    deadline = asyncio.get_event_loop().time() + seconds
    while asyncio.get_event_loop().time() < deadline:
        run = swarm.status(subagentId)
        if run.get("status") not in ("pending", "running", "in_review", "blocked"):
            return run
        await asyncio.sleep(0.02)
    return swarm.status(subagentId)


class TestCancelRun:
    @pytest.mark.asyncio
    async def test_cancel_running_background_task(self, swarm):
        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_slow_agent()):
            ack = await swarm.spawn(task="长任务", agent_id="researcher",
                                    session_id="s-parent", background=True)
        assert ack["status"] == "pending"
        result = swarm.cancelRun(ack["subagent_id"], reason="不再需要")
        assert result["success"] is True
        final = await _waitForTerminal(swarm, ack["subagent_id"])
        assert final["status"] == "failed"
        assert "subagent_cancelled" in final["error"], final["error"]
        # 槽位释放：该会话不再有活跃子代理
        assert swarm.pendingBackgroundForSession("s-parent")["active"] == []

    @pytest.mark.asyncio
    async def test_cancel_blocked_entry_fails_it_without_launch(self, swarm):
        # 前置是慢任务 → 下游因依赖未满足而 blocked
        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_slow_agent()):
            upstream = await swarm.spawn(task="前置慢任务", agent_id="researcher", background=True)
        unit = {"goal": "下游任务", "dependencies": [upstream["subagent_id"]]}
        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_quick_agent()):
            downstream = await swarm.spawn(task="下游任务", agent_id="researcher",
                                           task_unit=unit, background=True)
        assert downstream["status"] == "blocked"

        result = swarm.cancelRun(downstream["subagent_id"], reason="方向变了")
        assert result["success"] is True
        final = swarm.status(downstream["subagent_id"])
        assert final["status"] == "failed"
        assert "subagent_cancelled" in final["error"], final["error"]

        # 前置完成后，被叫停的下游不得再被依赖结算拉起
        swarm.cancelRun(upstream["subagent_id"])
        await _waitForTerminal(swarm, upstream["subagent_id"])
        assert swarm.status(downstream["subagent_id"])["status"] == "failed"

    @pytest.mark.asyncio
    async def test_cancel_terminal_is_honest_failure(self, swarm):
        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_quick_agent()):
            done = await swarm.spawn(task="秒完", agent_id="researcher")
        assert done["status"] == "completed"
        result = swarm.cancelRun(done["subagent_id"])
        assert result["success"] is False
        assert "已终态" in result["error"]

    def test_cancel_unknown_id(self, swarm):
        result = swarm.cancelRun("swarm_nope")
        assert result["success"] is False and "未找到" in result["error"]

    @pytest.mark.asyncio
    async def test_cancel_writes_event_log(self, swarm):
        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_slow_agent()):
            ack = await swarm.spawn(task="长任务", agent_id="researcher", background=True)
        swarm.cancelRun(ack["subagent_id"], reason="不再需要")
        await _waitForTerminal(swarm, ack["subagent_id"])
        events = readRunEvents(ack["subagent_id"])
        assert any(e["type"] == "cancelled" for e in events), "叫停事实必须入事件账本"


class TestUpdateRunningRun:
    @pytest.mark.asyncio
    async def test_continue_running_with_steer_injects_and_keeps_running(self, swarm):
        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_slow_agent(2.0)):
            ack = await swarm.spawn(task="长任务", agent_id="researcher", background=True)
        # 等成员真正进入 running（后台任务异步起步）
        deadline = asyncio.get_event_loop().time() + 2.0
        while asyncio.get_event_loop().time() < deadline:
            if swarm.status(ack["subagent_id"])["status"] == SUBAGENT_RUNNING:
                break
            await asyncio.sleep(0.02)
        memberSession = swarm.status(ack["subagent_id"])["member_session_id"]

        result = await swarm.updateSubagent(ack["subagent_id"], "需求变更：只做前半部分",
                                            mode="steer")
        assert result["success"] is True
        assert result["delivered"] == "steer"
        # 指令进了成员会话的插话队列（成员下一工具轮可见）
        assert "需求变更：只做前半部分" in get_steer_queue().drain(memberSession)
        # run 仍在运行，未被终止
        assert swarm.status(ack["subagent_id"])["status"] == SUBAGENT_RUNNING
        # 事件账本留痕
        assert any(e["type"] == "update_injected" for e in readRunEvents(ack["subagent_id"]))
        swarm.cancelRun(ack["subagent_id"])  # 清场

    @pytest.mark.asyncio
    async def test_continue_running_with_restart_cancels_and_respawns(self, swarm):
        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_slow_agent(2.0)):
            ack = await swarm.spawn(task="旧方向长任务", agent_id="researcher", background=True)
        oldId = ack["subagent_id"]

        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_quick_agent("按新方向完成")):
            result = await swarm.updateSubagent(oldId, "需求变更：改做新方向", mode="restart")

        # restart 的最终返回是新 run 的 spawn 结果（无 success 键）
        assert result["status"] == "completed"
        newId = result["subagent_id"]
        assert newId != oldId, "restart 必须重派新 run，不复用旧 id"
        final = await _waitForTerminal(swarm, newId)
        assert final["status"] == "completed"
        assert "按新方向完成" in final["report"]
        assert final["resumed_from"] == oldId, "重派必须保留续跑溯源"
        oldFinal = swarm.status(oldId)
        assert oldFinal["status"] == "failed"
        assert "subagent_cancelled" in oldFinal["error"], oldFinal["error"]

    @pytest.mark.asyncio
    async def test_continue_terminal_still_works(self, swarm):
        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_quick_agent("首跑完成")):
            done = await swarm.spawn(task="首跑", agent_id="researcher")
        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_quick_agent("续跑完成")):
            result = await swarm.updateSubagent(done["subagent_id"], "补充一点", mode="steer")
        # 终态续跑走既有链：返回的是新 run 的 spawn 结果（无 success 键）
        assert result["status"] == "completed"
        assert result["resumed_from"] == done["subagent_id"]

    @pytest.mark.asyncio
    async def test_update_requires_message(self, swarm):
        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_slow_agent(2.0)):
            ack = await swarm.spawn(task="长任务", agent_id="researcher", background=True)
        result = await swarm.updateSubagent(ack["subagent_id"], "  ", mode="steer")
        assert result["success"] is False
        swarm.cancelRun(ack["subagent_id"])


class TestToolSurface:
    def test_cancel_tool_registered_and_excluded_from_members(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        assert "cancel_subagent" in _BUILTIN_SCHEMAS
        allow = computeSubagentToolAllowlist("general")
        assert "cancel_subagent" not in allow, "成员不得叫停自己/兄弟的运行"
        assert "continue_subagent" not in allow
