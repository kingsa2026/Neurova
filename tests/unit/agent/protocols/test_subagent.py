"""子代理派生 (SubAgent) 单元测试。

对齐升级方案 P1-2.1：运行时子代理派生 —— Agent.spawn_subagent(role, task)
→ 独立上下文、可并发。含方案成功标准的并行「检索+生成」演示。
"""

import asyncio
import time
import unittest

from neurova.agent.subagent import (
    SubAgent,
    SubAgentManager,
    SubAgentResult,
    get_subagent_manager,
    reset_subagent_manager,
)


class TestSubAgentSpec(unittest.IsolatedAsyncioTestCase):
    """单个子代理的独立上下文与执行。"""

    async def test_run_invokes_executor_with_task_and_context(self):
        agent = SubAgent(role="retriever", task="检索 2024 财报", context={"year": 2024})

        async def executor(task, context):
            return f"done:{task}:{context['year']}"

        result = await agent.run(executor)
        self.assertIsInstance(result, SubAgentResult)
        self.assertTrue(result.success)
        self.assertEqual(result.output, "done:检索 2024 财报:2024")
        self.assertEqual(result.role, "retriever")

    async def test_context_is_isolated_copy(self):
        shared = {"k": "v"}
        agent = SubAgent(role="r", task="t", context=shared)
        await agent.run(lambda t, c: c.update({"mutated": True}) or "ok")
        # 独立上下文：修改不泄漏回调用方
        self.assertNotIn("mutated", shared)

    async def test_executor_failure_captured_not_raised(self):
        agent = SubAgent(role="r", task="boom")

        async def executor(t, c):
            raise ValueError("task exploded")

        result = await agent.run(executor)
        self.assertFalse(result.success)
        self.assertIn("exploded", result.error)

    async def test_trace_id_propagates(self):
        agent = SubAgent(role="r", task="t", trace_id="trace-9")
        seen = {}

        async def executor(t, c):
            seen.update(c)
            return "ok"

        await agent.run(executor)
        self.assertEqual(seen.get("trace_id"), "trace-9")


class TestConcurrentExecution(unittest.IsolatedAsyncioTestCase):
    """并发执行——方案成功标准：多子代理并行完成「检索+生成」。"""

    async def test_retrieval_and_generation_run_in_parallel(self):
        manager = SubAgentManager()

        async def slow_task(label, seconds):
            async def executor(t, c):
                await asyncio.sleep(seconds)
                return label
            return executor

        retriever = SubAgent(role="retriever", task="检索资料")
        generator = SubAgent(role="generator", task="生成回答")

        async def retrieval_exec(t, c):
            await asyncio.sleep(0.25)
            return "【检索结果】"

        async def generation_exec(t, c):
            await asyncio.sleep(0.25)
            return "【生成结果】"

        start = time.monotonic()
        results = await manager.run_all(
            [
                (retriever, retrieval_exec),
                (generator, generation_exec),
            ],
            concurrent=True,
        )
        elapsed = time.monotonic() - start

        outputs = [r.output for r in results]
        self.assertIn("【检索结果】", outputs)
        self.assertIn("【生成结果】", outputs)
        # 并行：总耗时接近单任务时长，而非两者之和（0.5s）
        self.assertLess(elapsed, 0.45, f"未并行执行，耗时 {elapsed:.2f}s")

    async def test_sequential_mode_supported(self):
        manager = SubAgentManager()
        order = []

        def make_exec(label):
            async def executor(t, c):
                order.append(label)
                return label
            return executor

        results = await manager.run_all(
            [
                (SubAgent(role="a", task="1"), make_exec("first")),
                (SubAgent(role="b", task="2"), make_exec("second")),
            ],
            concurrent=False,
        )
        self.assertEqual([r.output for r in results], ["first", "second"])
        self.assertEqual(order, ["first", "second"])


class TestSpawnAPI(unittest.TestCase):
    """spawn_subagent 便捷入口 + 单例生命周期。"""

    def setUp(self):
        reset_subagent_manager()

    def tearDown(self):
        reset_subagent_manager()

    def test_spawn_registers_subagent(self):
        mgr = get_subagent_manager()
        agent = mgr.spawn(role="reviewer", task="审查 PR #12", context={"pr": 12})
        self.assertIsInstance(agent, SubAgent)
        self.assertEqual(agent.role, "reviewer")
        self.assertTrue(agent.agent_id.startswith("sub-"))
        self.assertIn(agent.agent_id, [a.agent_id for a in mgr.list_spawned()])

    def test_spawned_agents_have_unique_ids(self):
        mgr = get_subagent_manager()
        a = mgr.spawn(role="a", task="t1")
        b = mgr.spawn(role="a", task="t2")
        self.assertNotEqual(a.agent_id, b.agent_id)

    def test_singleton_identity_and_reset(self):
        first = get_subagent_manager()
        self.assertIs(first, get_subagent_manager())
        reset_subagent_manager()
        self.assertIsNot(first, get_subagent_manager())


if __name__ == "__main__":
    unittest.main()
