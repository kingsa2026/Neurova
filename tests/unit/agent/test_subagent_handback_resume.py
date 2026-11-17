# -*- coding: utf-8 -*-
"""P2（工具清单 3.1-3 续）：失败交接与子代理续跑。

- 失败交接：子代理失败/取消时，已流式产出的 content 尾部落入 run.report
  （父代不再只拿到一句 error）；
- continue_subagent：对已终态的子代理续跑——member 会话键复用（历史由既有
  会话恢复带回）、上一段 report 附作衔接上下文、治理闸与全新派生同路；
- 面外拒绝：进行中的运行不可续跑、未知 ID/空指令诚实报错；
- 工具面：continue_subagent schema 注册、分派接线、子代理白名单排除。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.swarm import (
    SUBAGENT_FINISHED_STATUSES,
    SUBAGENT_RUNNING,
    SubAgentRun,
    SwarmManager,
    computeSubagentToolAllowlist,
    get_swarm_manager,
    reset_swarm_manager,
)
from neurova.builtin_tools import _BUILTIN_SCHEMAS


def make_streaming_agent(name="子Agent", chunks=(), error=None, reply="续跑完成"):
    """chat 时先流式吐 chunks、再按 error/reply 收尾的假子 Agent"""

    class StreamingAgent:
        def __init__(self):
            self.config = MagicMock()
            self.config.name = name
            self.chat = AsyncMock(side_effect=self._chat)

        async def _chat(self, task, **kwargs):
            emitter = (kwargs.get("metadata") or {}).get("event_emitter")
            for chunk in chunks:
                if emitter is not None:
                    emitter("content", chunk)
                await asyncio.sleep(0)
            if error is not None:
                raise error
            return {"text": reply}

    return StreamingAgent()


@pytest.fixture
def swarm():
    reset_swarm_manager()
    return get_swarm_manager()


class TestFailureHandback:
    """失败交接：部分报告随 failed run 上行"""

    @pytest.mark.asyncio
    async def test_failed_run_carries_partial_report(self, swarm):
        agent = make_streaming_agent(
            chunks=("已完成调研：", "结论 A；"), error=RuntimeError("上游 429 限流")
        )
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="长调研", agent_id="researcher")

        assert result["status"] == "failed"
        assert "429" in (result["error"] or "")
        # 部分报告非空且含失败前已产出的内容——父代据此续判/续跑
        assert "结论 A" in result["report"]

    @pytest.mark.asyncio
    async def test_failed_run_without_content_keeps_empty_report(self, swarm):
        agent = make_streaming_agent(error=RuntimeError("启动即崩"))
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="任务", agent_id="researcher")

        assert result["status"] == "failed"
        assert result["report"] == ""

    @pytest.mark.asyncio
    async def test_cancelled_run_carries_partial_report(self, swarm):
        agent = make_streaming_agent(chunks=("部分产出",), error=asyncio.CancelledError())
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            with pytest.raises(asyncio.CancelledError):
                await swarm.spawn(task="任务", agent_id="researcher")

        run = swarm.list_all(limit=1)[0]
        assert run["status"] == "failed"
        assert "部分产出" in run["report"]

    def test_partial_handback_tails_to_cap(self):
        buf = ["x" * 100] * 100  # 10000 字符
        partial = SwarmManager._partialHandback(buf)
        assert len(partial) == 4000


class TestResumeFinishedRun:
    """continue_subagent：终态子代理续跑"""

    def _seedFinished(self, swarm, status="failed", report="已有部分结论"):
        run = SubAgentRun(
            agent_id="researcher",
            agent_name="研究员",
            task="原任务",
            origin="chat",
            session_id="parent-s1",
            member_session_id="member-old",
        )
        run.status = status
        run.report = report
        swarm._runs[run.subagent_id] = run
        return run

    @pytest.mark.asyncio
    async def test_resume_failed_run_reuses_member_session_and_hands_off(self, swarm):
        old = self._seedFinished(swarm, status="failed", report="部分结论 ABC")
        agent = make_streaming_agent(reply="续跑补全结论")
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.resumeFinishedRun(
                old.subagent_id, "接着把结论 B 补全", session_id="parent-s2"
            )

        assert result["status"] == "completed"
        assert result["report"] == "续跑补全结论"
        # 复活溯源：新 run 挂着被续跑那条的 ID
        assert result["resumed_from"] == old.subagent_id
        assert result["subagent_id"] != old.subagent_id
        # member 会话键原样复用——历史由既有会话恢复机制带回
        assert result["member_session_id"] == old.member_session_id
        # 续跑任务 = 衔接上下文 + 新指令
        task = agent.chat.call_args.args[0]
        kwargs = agent.chat.call_args.kwargs
        assert kwargs["session_id"] == old.member_session_id
        assert "部分结论 ABC" in task
        assert "接着把结论 B 补全" in task

    @pytest.mark.asyncio
    async def test_resume_completed_run_appends_message(self, swarm):
        old = self._seedFinished(swarm, status="completed", report="首轮报告")
        agent = make_streaming_agent(reply="追加分析完成")
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.resumeFinishedRun(old.subagent_id, "再深挖一层")

        assert result["status"] == "completed"
        task = agent.chat.call_args.args[0]
        assert "首轮报告" in task and "再深挖一层" in task

    @pytest.mark.asyncio
    async def test_resume_rejects_running_run(self, swarm):
        old = self._seedFinished(swarm)
        old.status = SUBAGENT_RUNNING
        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")
        assert "error" in result and "仍在运行" in result["error"]

    @pytest.mark.asyncio
    async def test_resume_unknown_id_errors(self, swarm):
        result = await swarm.resumeFinishedRun("swarm_nope", "继续")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_resume_requires_message(self, swarm):
        old = self._seedFinished(swarm)
        result = await swarm.resumeFinishedRun(old.subagent_id, "  ")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_finished_statuses_cover_terminal_runs(self):
        assert {"completed", "failed"} <= SUBAGENT_FINISHED_STATUSES


class TestContinueSubagentTool:
    """工具面：schema 注册 + 分派接线 + 白名单排除"""

    def test_schema_registered(self):
        assert "continue_subagent" in _BUILTIN_SCHEMAS
        spec = _BUILTIN_SCHEMAS["continue_subagent"]
        assert set(spec["parameters"]["required"]) == {"subagent_id", "message"}

    def test_general_allowlist_excludes_recursive_coordination(self):
        allow = computeSubagentToolAllowlist("general")
        assert "spawn_subagent" not in allow
        assert "continue_subagent" not in allow

    @pytest.mark.asyncio
    async def test_executor_passes_session_and_background(self):
        from neurova.tool_executor import ToolExecutor

        agent = MagicMock()
        agent.current_session_id = "sess-abc"
        exe = ToolExecutor(agent)
        fake_swarm = MagicMock()
        # H 批补差：continue 统一经 updateSubagent（终态走续跑链、运行中走改需求）
        fake_swarm.updateSubagent = AsyncMock(return_value={"status": "completed"})
        with patch("neurova.agent.swarm.get_swarm_manager", return_value=fake_swarm):
            result = await exe._execute_continue_subagent(
                {"subagent_id": "swarm_x", "message": "继续", "background": True}
            )

        assert result["status"] == "completed"
        fake_swarm.updateSubagent.assert_awaited_once()
        args, kwargs = fake_swarm.updateSubagent.call_args
        assert args[0] == "swarm_x" and args[1] == "继续"
        assert kwargs["session_id"] == "sess-abc"
        assert kwargs["background"] is True
        assert kwargs["mode"] == "steer"

    @pytest.mark.asyncio
    async def test_executor_requires_ids(self):
        from neurova.tool_executor import ToolExecutor

        exe = ToolExecutor(MagicMock())
        assert "error" in await exe._execute_continue_subagent({"message": "x"})
        assert "error" in await exe._execute_continue_subagent({"subagent_id": "s"})
