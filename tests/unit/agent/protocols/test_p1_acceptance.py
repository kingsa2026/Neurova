"""P1 阶段验收测试。

对照升级方案 2.2 成功标准：
- 多子代理示例能并行完成「检索+生成」两段任务
- Agent.spawn_subagent 委托入口可用（agent_core 只做委托）
- AgentTeam 能按角色编排一次完整协作链路
"""

import asyncio
import time
import unittest

from neurova.agent.protocols.acp_runtime import ACPRuntime
from neurova.agent.subagent import reset_subagent_manager
from neurova.agent.team import AgentTeam
from neurova.agent.templates.collaboration_template import AgentRole


class TestP1Acceptance(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        reset_subagent_manager()

    async def asyncTearDown(self):
        reset_subagent_manager()

    async def test_parallel_retrieval_and_generation_demo(self):
        """方案验收: 子代理并行完成「检索+生成」。"""
        from neurova.agent.subagent import get_subagent_manager

        mgr = get_subagent_manager()
        retriever = mgr.spawn(role="retriever", task="检索记忆", trace_id="trace-accept")
        generator = mgr.spawn(role="generator", task="生成回复", trace_id="trace-accept")

        async def retrieve(task, ctx):
            await asyncio.sleep(0.2)
            return {"chunks": ["事实A", "事实B"]}

        async def generate(task, ctx):
            await asyncio.sleep(0.2)
            return {"reply": "基于检索结果的回答"}

        start = time.monotonic()
        results = await mgr.run_all(
            [(retriever, retrieve), (generator, generate)], concurrent=True
        )
        elapsed = time.monotonic() - start

        self.assertTrue(all(r.success for r in results))
        self.assertLess(elapsed, 0.4, "两个子代理未并行执行")
        # 同一业务链路共享 trace_id
        self.assertEqual({r.trace_id for r in results}, {"trace-accept"})

    async def test_team_orchestration_end_to_end(self):
        """方案验收: 按角色编排 检索→生成→审查 协作链路。"""
        rt = ACPRuntime()
        team = AgentTeam(runtime=rt)

        pipeline = {}

        def retriever_handler(msg):
            pipeline["retrieved"] = True
            return msg.create_response(True, result={"chunks": ["x"]})

        def author_handler(msg):
            assert pipeline.get("retrieved"), "作者应拿到检索产物后才开始"
            pipeline["drafted"] = True
            return msg.create_response(True, result={"draft": "初稿"})

        def reviewer_handler(msg):
            assert pipeline.get("drafted"), "审查者应在初稿之后"
            return msg.create_response(True, result={"approved": True})

        team.add_member("r", AgentRole.PARTICIPANT, retriever_handler)
        team.add_member("a", AgentRole.AUTHOR, author_handler)
        team.add_member("v", AgentRole.REVIEWER, reviewer_handler)

        outcome = await team.orchestrate(
            goal="回答用户关于项目的问题",
            steps=[
                {"role": AgentRole.PARTICIPANT, "action": "retrieve"},
                {"role": AgentRole.AUTHOR, "action": "draft"},
                {"role": AgentRole.REVIEWER, "action": "review"},
            ],
        )
        self.assertTrue(outcome.success)
        self.assertEqual([s.action for s in outcome.steps], ["retrieve", "draft", "review"])

    def test_agent_spawn_subagent_delegation(self):
        """agent_core 只做委托：spawn_subagent 转发到 SubAgentManager。"""
        from neurova.agent_core import Agent

        agent = object.__new__(Agent)  # 绕过重量级 __init__
        sub = agent.spawn_subagent("reviewer", "审查 PR", context={"pr": 12})
        self.assertEqual(sub.role, "reviewer")
        self.assertEqual(sub.context["pr"], 12)


if __name__ == "__main__":
    unittest.main()
