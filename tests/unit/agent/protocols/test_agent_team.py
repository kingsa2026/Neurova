"""AgentTeam 多角色编排单元测试。

对齐升级方案 P1-2.1：复用 AgentRole 角色定义，把「同一实例多角色」
升级为基于 ACP 消息的多 agent 标准协议编排。
"""

import unittest

from neurova.agent.protocols.acp_runtime import ACPRuntime
from neurova.agent.team import AgentTeam, TeamStepResult
from neurova.agent.templates.collaboration_template import AgentRole


def _make_team() -> tuple:
    rt = ACPRuntime()
    return rt, AgentTeam(runtime=rt)


class TestMembership(unittest.IsolatedAsyncioTestCase):
    """成员注册与角色分配。"""

    async def test_add_member_registers_into_runtime(self):
        rt, team = _make_team()
        team.add_member("agent-a", AgentRole.AUTHOR, lambda m: m.create_response(True, "ok"))
        self.assertIn("agent-a", rt.list_agents())

    async def test_get_role_agents(self):
        _, team = _make_team()
        team.add_member("author-1", AgentRole.AUTHOR, lambda m: None)
        team.add_member("reviewer-1", AgentRole.REVIEWER, lambda m: None)
        self.assertEqual(team.get_role_agents(AgentRole.AUTHOR), ["author-1"])

    async def test_duplicate_role_allowed_multiple_members(self):
        _, team = _make_team()
        team.add_member("rev-1", AgentRole.REVIEWER, lambda m: None)
        team.add_member("rev-2", AgentRole.REVIEWER, lambda m: None)
        self.assertEqual(len(team.get_role_agents(AgentRole.REVIEWER)), 2)


class TestOrchestration(unittest.IsolatedAsyncioTestCase):
    """多步骤任务编排。"""

    async def test_orchestrate_dispatches_by_role(self):
        rt, team = _make_team()
        calls = []

        def author_handler(msg):
            calls.append(("author", msg.action))
            return msg.create_response(success=True, result={"draft": "v1"})

        def reviewer_handler(msg):
            calls.append(("reviewer", msg.action))
            return msg.create_response(success=True, result={"approved": True})

        team.add_member("a1", AgentRole.AUTHOR, author_handler)
        team.add_member("r1", AgentRole.REVIEWER, reviewer_handler)

        result = await team.orchestrate(
            goal="发布新功能",
            steps=[
                {"role": AgentRole.AUTHOR, "action": "draft", "params": {"topic": "feature"}},
                {"role": AgentRole.REVIEWER, "action": "review", "params": {}},
            ],
        )

        self.assertEqual(calls[0], ("author", "draft"))
        self.assertEqual(calls[1], ("reviewer", "review"))
        self.assertTrue(result.success)
        self.assertEqual(len(result.steps), 2)

    async def test_step_results_carry_outputs(self):
        _, team = _make_team()

        def solver(msg):
            return msg.create_response(success=True, result={"answer": "42"})

        team.add_member("s1", AgentRole.SOLVER, solver)
        result = await team.orchestrate(
            goal="解题",
            steps=[{"role": AgentRole.SOLVER, "action": "solve"}],
        )
        step = result.steps[0]
        self.assertIsInstance(step, TeamStepResult)
        self.assertEqual(step.result.get("answer"), "42")

    async def test_shared_trace_id_across_steps(self):
        _, team = _make_team()
        traces = []

        def handler(msg):
            traces.append(msg.trace_id)
            return msg.create_response(True, "ack")

        team.add_member("m1", AgentRole.PARTICIPANT, handler)
        await team.orchestrate(
            goal="链路",
            steps=[
                {"role": AgentRole.PARTICIPANT, "action": "step1"},
                {"role": AgentRole.PARTICIPANT, "action": "step2"},
            ],
        )
        # 同一次编排共享一个 trace_id，贯穿所有步骤
        self.assertEqual(len(set(traces)), 1)
        self.assertIsNotNone(traces[0])

    async def test_missing_role_marks_step_failed_not_crash(self):
        _, team = _make_team()
        result = await team.orchestrate(
            goal="空团队",
            steps=[{"role": AgentRole.DIAGNOSTIC, "action": "diagnose"}],
        )
        self.assertFalse(result.success)
        self.assertFalse(result.steps[0].success)

    async def test_step_failure_does_not_stop_later_steps(self):
        _, team = _make_team()
        executed = []

        def flaky(msg):
            if msg.action == "fail":
                raise RuntimeError("no")
            executed.append(msg.action)
            return msg.create_response(True, msg.action)

        team.add_member("p", AgentRole.PARTICIPANT, flaky)
        result = await team.orchestrate(
            goal="容错",
            steps=[
                {"role": AgentRole.PARTICIPANT, "action": "fail"},
                {"role": AgentRole.PARTICIPANT, "action": "recover"},
            ],
        )
        self.assertFalse(result.steps[0].success)
        self.assertTrue(result.steps[1].success)
        self.assertIn("recover", executed)


if __name__ == "__main__":
    unittest.main()
