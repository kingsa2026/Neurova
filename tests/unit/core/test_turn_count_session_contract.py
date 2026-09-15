"""会话级轮次计数契约测试（2026-09-15 反思/成长链路排查修复）

根因: turn_count 原为 ContextVar——uvicorn 每请求在独立 task 上下文执行，
set() 的值不跨请求传播 → increment 后恒 1，post_chat_pipeline 周期反思门控
`turn_count % 10 == 0` 数学上永不成立，"每 N 轮强制反思"形同虚设。
轮次号的真实语义是"会话内第几轮"（幂等键/任务号消费方只需要本轮唯一值），
应跨请求按会话持久累积。
"""

import asyncio
import unittest

from neurova.core.turn_context import (
    clear_turn_state,
    get_turn_count,
    increment_turn_count,
    set_turn_identity,
)


def _one_request(session_id: str) -> int:
    """模拟一次 chat 请求：独立 asyncio task（uvicorn 每请求复制创建时 context，
    ContextVar.set 不外泄）→ 轮次号必须仍跨请求累积。"""

    async def _req() -> int:
        set_turn_identity("你好", session_id=session_id, user_id="u1")
        increment_turn_count()
        return get_turn_count()

    return asyncio.run(_req())


class TurnCountSessionContractTest(unittest.TestCase):
    def setUp(self):
        clear_turn_state()

    def tearDown(self):
        clear_turn_state()

    def test_accumulates_across_request_tasks(self):
        counts = [_one_request("sess-a") for _ in range(12)]
        self.assertEqual(
            counts,
            list(range(1, 13)),
            "轮次号必须跨请求在会话内单调累积（修复前恒为 [1,1,...]）",
        )

    def test_sessions_are_isolated(self):
        self.assertEqual(_one_request("sess-a"), 1)
        self.assertEqual(_one_request("sess-b"), 1)
        self.assertEqual(_one_request("sess-a"), 2)

    def test_no_session_falls_back_to_default_bucket(self):
        async def _req() -> int:
            set_turn_identity("你好", session_id=None, user_id="u1")
            increment_turn_count()
            return get_turn_count()

        self.assertEqual(asyncio.run(_req()), 1)
        self.assertEqual(asyncio.run(_req()), 2)

    def test_clear_turn_state_resets_all_sessions(self):
        _one_request("sess-a")
        _one_request("sess-b")
        clear_turn_state()
        self.assertEqual(_one_request("sess-a"), 1, "clear 后会话计数必须归零（测试隔离契约）")


class PeriodicReflectionGateTest(unittest.TestCase):
    """post_chat Step 8.5 周期反思门控必须在第 10 轮真实触发"""

    def _pipeline(self):
        from neurova.post_chat_pipeline import PostChatPipeline

        class _Agent:
            @property
            def turn_count(self) -> int:
                return get_turn_count()

        return PostChatPipeline(_Agent())

    def test_fires_exactly_at_turn_10(self):
        clear_turn_state()
        pipeline = self._pipeline()
        # 关键词全不命中的中性输入/回复；生产链路里 Step 8.5 与身份绑定同处
        # 请求上下文，故在模拟请求 task 内评估门控
        user, reply = "你好", "你好呀，很高兴见到你"

        def _one_turn() -> bool:
            async def _req() -> bool:
                set_turn_identity(user, session_id="sess-r", user_id="u1")
                increment_turn_count()
                return pipeline._should_reflect(user, reply)

            return asyncio.run(_req())

        for turn in range(1, 10):
            self.assertFalse(_one_turn(), f"turn {turn} 无关键词命中时不应触发反思")
        self.assertTrue(_one_turn(), "turn 10 必须触发周期性反思（修复前门控恒假）")


if __name__ == "__main__":
    unittest.main()
