# -*- coding: utf-8 -*-
"""
P1-a RecallLoopGuard 防回归网（对标 QP beta.5 RecallLoopGuard + 双指纹 cursor）

语义（适配 NV 单执行器架构）：
- 请求指纹 = sha256(query|limit)：同指纹再次调用时比对**结果快照指纹**
  （召回内容的 sha256）——同查询同结果 = 死循环风险 → DENY；
  同查询但结果已变（台账更新）→ ALLOW 并更新快照
- 轮次边界：chat_pipeline Step0 显式 reset（一次对话一轮）
"""
import pytest


class TestRecallLoopGuard:
    def test_first_query_allowed(self):
        from neurova.agent.recall_loop_guard import RecallLoopGuard

        guard = RecallLoopGuard()
        allowed, reason = guard.record_and_check("分析数据", 10, digest="aaa")
        assert allowed is True
        assert reason is None

    def test_same_query_same_result_denied(self):
        from neurova.agent.recall_loop_guard import RecallLoopGuard

        guard = RecallLoopGuard()
        guard.record_and_check("分析数据", 10, digest="aaa")
        allowed, reason = guard.record_and_check("分析数据", 10, digest="aaa")
        assert allowed is False
        assert reason and ("已召回" in reason or "重复" in reason)

    def test_same_query_changed_result_allowed(self):
        """同查询但结果快照漂移（台账更新）→ 放行并更新"""
        from neurova.agent.recall_loop_guard import RecallLoopGuard

        guard = RecallLoopGuard()
        guard.record_and_check("分析数据", 10, digest="aaa")
        allowed, reason = guard.record_and_check("分析数据", 10, digest="bbb")
        assert allowed is True
        # 再查旧结果（数据回滚）→ 又允许（快照已更新为 bbb，aaa 视为漂移）
        allowed2, _ = guard.record_and_check("分析数据", 10, digest="aaa")
        assert allowed2 is True

    def test_different_limit_is_different_query(self):
        from neurova.agent.recall_loop_guard import RecallLoopGuard

        guard = RecallLoopGuard()
        guard.record_and_check("分析数据", 10, digest="aaa")
        allowed, _ = guard.record_and_check("分析数据", 20, digest="aaa")
        assert allowed is True

    def test_reset_clears_state(self):
        from neurova.agent.recall_loop_guard import RecallLoopGuard

        guard = RecallLoopGuard()
        guard.record_and_check("分析数据", 10, digest="aaa")
        guard.reset()
        allowed, _ = guard.record_and_check("分析数据", 10, digest="aaa")
        assert allowed is True  # 新轮次

    def test_digest_computed_from_recall_content(self):
        """结果快照指纹应由召回内容计算（compute_digest 语义）"""
        from neurova.agent.recall_loop_guard import compute_digest

        d1 = compute_digest([{"content": "abc", "turn_id": 1}])
        d2 = compute_digest([{"content": "abc", "turn_id": 1}])
        d3 = compute_digest([{"content": "abd", "turn_id": 1}])
        assert d1 == d2
        assert d1 != d3


class TestExecutorWiring:
    """tool_executor 接线：同轮重复同结果召回 → 拒绝信封（非死循环）"""

    def _make_executor(self, recalled_items):
        from neurova.tool_executor import ToolExecutor
        from types import SimpleNamespace

        executor = ToolExecutor.__new__(ToolExecutor)
        executor._agent = SimpleNamespace(
            context_orchestrator=SimpleNamespace(
                context_pool=SimpleNamespace(
                    recall_evicted=lambda query, limit: recalled_items
                )
            ),
            turn_count=1,
        )
        return executor

    @pytest.mark.asyncio
    async def test_second_identical_recall_rejected(self):
        from neurova.context.pool_models import ContextInput, ContextSource

        items = [
            ContextInput(source=ContextSource.MEMORY, content="被折叠的历史 X", priority=50)
        ]
        executor = self._make_executor(items)

        r1 = await executor._execute_recall_history({"query": "历史 X", "limit": 5})
        assert r1["success"] is True

        r2 = await executor._execute_recall_history({"query": "历史 X", "limit": 5})
        # 同查询同结果 → 拒绝（防死循环），信封带指引
        assert r2["success"] is False
        assert "已召回" in r2["error"] or "重复" in r2["error"]

    @pytest.mark.asyncio
    async def test_new_turn_resets_guard(self):
        from neurova.context.pool_models import ContextInput, ContextSource

        items = [ContextInput(source=ContextSource.MEMORY, content="历史 Y", priority=50)]
        executor = self._make_executor(items)

        await executor._execute_recall_history({"query": "历史 Y"})
        executor._agent.turn_count = 2  # 新轮次
        r = await executor._execute_recall_history({"query": "历史 Y"})
        assert r["success"] is True  # 轮次重置后允许


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
