"""
P1-1④ ack 集 + 分层剪枝测试

语义：
- ContextInput.seen_confirmed：已被成功模型请求读过的标志（默认 False）
- ContextPool.mark_hashes_seen：ack 写入（唯一通路：编排器按视图 hash 标记）
- orchestrator.mark_last_view_seen：确认最近一次视图内的 chunk 已读
- Drawer 分层：未读 TOOL_CALL 优先入选（必须在模型视野内）；
  已确认的排后——超预算时先被跳过（第一层剪枝）

B6-10（Issue #90 审计 §5）：池上的旁路 ack `ContextPool.mark_turn_seen` 与其
配套的 turn 索引生产零消费，已删净；下面把「未读工具结果优先入选」这条契约
搬到它真正的承载面（`SemanticMatchDrawer.draw` 的分层选取）上用例钉住。
"""

import pytest

from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context_pool import ContextPool


def _tool_chunk(content, tokens=10, turn_id=None, seen=False):
    c = ContextInput(
        source=ContextSource.TOOL_CALL,
        content=content,
        tokens=tokens,
    )
    if turn_id:
        c.metadata["turn_id"] = turn_id
        c.metadata["pairs_with"] = turn_id
    if seen:
        c.seen_confirmed = True
    return c


def _conv_chunk(content, tokens=10, turn_id=None):
    c = ContextInput(
        source=ContextSource.CONVERSATION,
        content=content,
        tokens=tokens,
    )
    if turn_id:
        c.metadata["turn_id"] = turn_id
    return c


class TestSeenConfirmedField:
    def test_default_false(self):
        c = ContextInput(source=ContextSource.CONVERSATION, content="x")
        assert c.seen_confirmed is False


class TestPoolAck:
    def test_mark_hashes_seen(self):
        pool = ContextPool(user_id="u", agent_id="a")
        chunk = _conv_chunk("target")
        pool.add_context(chunk)
        count = pool.mark_hashes_seen([chunk.hash])
        assert count == 1
        assert pool.get_contexts()[0].seen_confirmed is True

    def test_mark_empty_hashes_noop(self):
        pool = ContextPool(user_id="u", agent_id="a")
        pool.add_context(_conv_chunk("x"))
        assert pool.mark_hashes_seen([]) == 0


class TestDrawerPrefersUnreadToolResults:
    """未读工具结果优先入选（契约从已退役的 select_fold_candidates 搬到真面）。

    `ContextPool.select_fold_candidates` 是最初的承载面，但它生产零消费（池上
    没有折叠路径，窗口折叠在 `window_compactor`），B6-10 删净。真正在生产的
    分层选取是 `SemanticMatchDrawer.draw` 的 `layered_positions`：未读
    TOOL_CALL 排在第 1 层、已确认的排第 2 层，超预算时先跳过后者。

    本类把契约钉在真面上：预算只够一条时，留下的必须是**没被模型看过**的那条。
    """

    def _draw_with_budget(self, drops, budget):
        from neurova.context.semantic_drawer import SemanticMatchDrawer

        return SemanticMatchDrawer(max_tokens=budget).draw(list(drops), need=None)

    def test_unread_tool_result_wins_under_tight_budget(self):
        unread = _tool_chunk("unseen result", tokens=40, turn_id="t1", seen=False)
        seen = _tool_chunk("already read", tokens=40, turn_id="t2", seen=True)
        # 插入序刻意把已读的放前面——按位置序选取会选错
        selected = self._draw_with_budget([seen, unread], budget=60)
        assert [d.content for d in selected] == ["unseen result"], (
            "预算不足时被跳过的应是已确认读过的条目；未读工具结果必须在视野内"
        )

    def test_seen_tool_result_still_eligible_when_budget_allows(self):
        unread = _tool_chunk("unseen result", tokens=40, turn_id="t1", seen=False)
        seen = _tool_chunk("already read", tokens=40, turn_id="t2", seen=True)
        selected = self._draw_with_budget([seen, unread], budget=500)
        assert {d.content for d in selected} == {"unseen result", "already read"}, (
            "预算充足时两层都应入选——分层只影响超预算时的跳过顺序"
        )


class TestOrchestratorAck:
    def test_mark_last_view_seen_marks_pool_chunks(self):
        from neurova.context.orchestrator import ContextOrchestrator
        from unittest.mock import MagicMock

        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "t"
        mock_agent.conversation_history = []
        orch = ContextOrchestrator(mock_agent)

        chunk = _conv_chunk("in view content")
        orch.context_pool.add_context(chunk)
        orch._last_view_hashes = {chunk.hash}

        assert orch.mark_last_view_seen() == 1
        assert orch.context_pool.get_contexts()[0].seen_confirmed is True

    def test_mark_last_view_seen_empty_noop(self):
        from neurova.context.orchestrator import ContextOrchestrator
        from unittest.mock import MagicMock

        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "t"
        mock_agent.conversation_history = []
        orch = ContextOrchestrator(mock_agent)
        assert orch.mark_last_view_seen() == 0  # 无视图 hash：no-op 不抛


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
