"""
P1-1④ ack 集 + 分层剪枝测试

语义（对标 QP scroll "已读才可折叠"）：
- ContextInput.seen_confirmed：已被成功模型请求读过的标志（默认 False）
- ContextPool.mark_turn_seen / mark_hashes_seen：ack 写入
- orchestrator.mark_last_view_seen：确认最近一次视图内的 chunk 已读
- Drawer 分层：未读 TOOL_CALL 优先入选（必须在模型视野内）；
  已确认的作为折叠候选排后——超预算时先被跳过（第一层剪枝）
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
    def test_mark_turn_seen_flips_matching_chunks(self):
        pool = ContextPool(user_id="u", agent_id="a")
        pool.add_context(_tool_chunk("t1 result", turn_id="turn_1"))
        pool.add_context(_tool_chunk("t2 result", turn_id="turn_2"))

        count = pool.mark_turn_seen("turn_1")

        assert count == 1
        chunks = pool.get_contexts()
        by_content = {c.content: c.seen_confirmed for c in chunks}
        assert by_content["t1 result"] is True
        assert by_content["t2 result"] is False

    def test_mark_turn_seen_idempotent(self):
        pool = ContextPool(user_id="u", agent_id="a")
        pool.add_context(_tool_chunk("r", turn_id="turn_1"))
        assert pool.mark_turn_seen("turn_1") == 1
        assert pool.mark_turn_seen("turn_1") == 0  # 已标记不再计数

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


class TestFoldCandidates:
    def test_fold_candidates_only_confirmed_tool_calls(self):
        """折叠候选 = 已确认的 TOOL_CALL（最老优先）；未读/其他源不入选"""
        pool = ContextPool(user_id="u", agent_id="a")
        pool.add_context(_tool_chunk("seen old", turn_id="turn_1", seen=True))
        pool.add_context(_tool_chunk("unseen fresh", turn_id="turn_2", seen=False))
        pool.add_context(_conv_chunk("conversation", turn_id="turn_3"))

        candidates = pool.select_fold_candidates()

        contents = [c.content for c in candidates]
        assert contents == ["seen old"]  # 只收已确认 TOOL_CALL

    def test_fold_candidates_oldest_first(self):
        from datetime import datetime, timedelta

        pool = ContextPool(user_id="u", agent_id="a")
        c_later = _tool_chunk("later", turn_id="turn_2", seen=True)
        c_earlier = _tool_chunk("earlier", turn_id="turn_1", seen=True)
        c_later.created_at = datetime.now()  # Windows 同毫秒打平 → 显式错开
        c_earlier.created_at = datetime.now() - timedelta(seconds=1)
        pool.add_context(c_later)
        pool.add_context(c_earlier)
        contents = [c.content for c in pool.select_fold_candidates()]
        assert contents == ["earlier", "later"]

    def test_fold_candidates_max_count(self):
        pool = ContextPool(user_id="u", agent_id="a")
        for i in range(5):
            pool.add_context(_tool_chunk(f"t{i}", turn_id=f"turn_{i}", seen=True))
        assert len(pool.select_fold_candidates(max_count=2)) == 2

    def test_unread_tool_never_fold_candidate(self):
        """核心不变量：未读工具结果绝不进折叠候选（防折叠致幻觉）"""
        pool = ContextPool(user_id="u", agent_id="a")
        pool.add_context(_tool_chunk("unseen", turn_id="turn_1", seen=False))
        assert pool.select_fold_candidates() == []


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
