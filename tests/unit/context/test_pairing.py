"""
P1-1① 上下文管线期① — 配对完整性红绿测试

孤儿场景：Drawer 按相关性/预算整条选取视图，可能出现 TOOL_CALL 被选入
而其所属轮次（pairs_with → turn_id）未选入。残缺视图让 LLM 看到
"无上下文的工具结果"，诱发幻觉。
"""

import pytest

from neurova.context.pairing import validate_pairing
from neurova.context.pool_models import ContextInput, ContextSource


def _chunk(source: str, content: str, turn_id=None, pairs_with=None, hash_=None, tokens=0):
    c = ContextInput(
        source=ContextSource[source],
        content=content,
        tokens=tokens,
    )
    if turn_id:
        c.metadata["turn_id"] = turn_id
    if pairs_with:
        c.metadata["pairs_with"] = pairs_with
    if hash_:
        c.hash = hash_
    return c


class TestValidatePairing:
    def test_orphan_tool_call_dropped(self):
        view = [
            _chunk("CONVERSATION", "user turn", turn_id="t1"),
            _chunk("TOOL_CALL", "orphan result", pairs_with="t_missing"),
        ]
        report = validate_pairing(view)
        assert [c.content for c in report.kept] == ["user turn"]
        assert report.orphan_count == 1
        assert report.orphans[0].content == "orphan result"

    def test_paired_tool_call_kept(self):
        view = [
            _chunk("CONVERSATION", "user turn", turn_id="t1"),
            _chunk("TOOL_CALL", "result", pairs_with="t1"),
        ]
        report = validate_pairing(view)
        assert report.orphan_count == 0
        assert len(report.kept) == 2

    def test_pairs_with_hash_target_supported(self):
        target_hash = "abc123"
        view = [
            _chunk("CONVERSATION", "user turn", hash_=target_hash),
            _chunk("TOOL_CALL", "result", pairs_with=target_hash),
        ]
        report = validate_pairing(view)
        assert report.orphan_count == 0

    def test_tool_call_without_pairs_with_is_self_contained(self):
        view = [_chunk("TOOL_CALL", "standalone record")]
        report = validate_pairing(view)
        assert report.orphan_count == 0

    def test_non_tool_call_never_orphan(self):
        view = [_chunk("CONVERSATION", "x", pairs_with="ghost")]
        report = validate_pairing(view)
        assert report.orphan_count == 0 and len(report.kept) == 1

    def test_kept_preserves_original_order(self):
        view = [
            _chunk("CONVERSATION", "a", turn_id="t1"),
            _chunk("TOOL_CALL", "orphan", pairs_with="ghost"),
            _chunk("CONVERSATION", "b", turn_id="t2"),
        ]
        report = validate_pairing(view)
        assert [c.content for c in report.kept] == ["a", "b"]

    def test_empty_view(self):
        report = validate_pairing([])
        assert report.kept == [] and report.orphans == []


class TestPoolDrawIntegratesPairing:
    def test_draw_drops_orphan_tool_call(self):
        """红测核心：Drawer 预算选取产生的孤儿必须在视图出口被剔除。

        构造：conversation chunk 超预算（500 tokens vs 池 100），tool_call
        极小被选中——预算选取天然制造孤儿。
        """
        from neurova.context_pool import ContextPool

        pool = ContextPool(user_id="u", agent_id="a", max_tokens=100)
        pool.add_context(_chunk("CONVERSATION", "big turn", turn_id="t1", tokens=500))
        pool.add_context(_chunk("TOOL_CALL", "tiny result", pairs_with="t1", tokens=10))

        view = pool.draw()

        assert all(c.source != ContextSource.TOOL_CALL for c in view), (
            f"孤儿 TOOL_CALL 泄入视图: {[c.content for c in view]}"
        )

    def test_draw_keeps_paired_tool_call(self):
        from neurova.context_pool import ContextPool

        pool = ContextPool(user_id="u", agent_id="a", max_tokens=100)
        pool.add_context(_chunk("CONVERSATION", "turn", turn_id="t1", tokens=20))
        pool.add_context(_chunk("TOOL_CALL", "result", pairs_with="t1", tokens=10))

        view = pool.draw()
        sources = [c.source for c in view]
        assert ContextSource.TOOL_CALL in sources
        assert ContextSource.CONVERSATION in sources


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
