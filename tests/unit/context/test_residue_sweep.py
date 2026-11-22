"""
P2-9 上下文工程 — 残留清理两遍扫描（红→绿）

空壳 assistant 形态：content 空/空白 且 无 tool_calls 且 无 tool_call_id
——中断/失败轮的占位残留入库后，发给模型是纯噪声。

两遍扫描单源在 pairing.py（视图出口洁净度的既有单源，教义第 6 条）：
- 第一遍：既有 validate_pairing 的孤儿 TOOL_CALL 判定（不复制、不回退）
- 第二遍：对第一遍 kept 再剔空壳 assistant 残留

接线面只有 ContextPool.draw（视图出口）；search 是主动召回工具面，
不接第二遍清扫（行为不漂移）。
"""

import pytest

from neurova.context.pairing import (
    isEmptyAssistantResidue,
    sweepResidues,
    validate_pairing,
)
from neurova.context.pool_models import ContextInput, ContextSource


def _conv_chunk(content, role="assistant", turn_id="t1", tokens=0):
    """构造 CONVERSATION 源 chunk（metadata 带 role，同编排器归档形态）。"""
    c = ContextInput(source=ContextSource.CONVERSATION, content=content, tokens=tokens)
    c.metadata["role"] = role
    if turn_id:
        c.metadata["turn_id"] = turn_id
    return c


def _tool_chunk(content, pairs_with=None, tool_call_id=None, tokens=0):
    """构造 TOOL_CALL 源 chunk（metadata 带 role/tool_call_id/pairs_with）。"""
    c = ContextInput(source=ContextSource.TOOL_CALL, content=content, tokens=tokens)
    c.metadata["role"] = "tool"
    if pairs_with:
        c.metadata["pairs_with"] = pairs_with
    if tool_call_id:
        c.metadata["tool_call_id"] = tool_call_id
    return c


def _tool_call_message(call_id="c1"):
    return [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
        }
    ]


class TestIsEmptyAssistantResidue:
    def testEmptyContentAssistantIsResidue(self):
        assert isEmptyAssistantResidue(_conv_chunk("")) is True

    def testWhitespaceContentAssistantIsResidue(self):
        assert isEmptyAssistantResidue(_conv_chunk("  \n\t ")) is True

    def testNoneContentAssistantIsResidue(self):
        assert isEmptyAssistantResidue(_conv_chunk(None)) is True

    def testNormalAssistantNotResidue(self):
        assert isEmptyAssistantResidue(_conv_chunk("北京今天晴，26 度。")) is False

    def testDictAssistantEmptyIsResidue(self):
        """鸭子类型：dict 消息（role 在顶层字段）同样判定。"""
        assert isEmptyAssistantResidue({"role": "assistant", "content": ""}) is True

    def testDictAssistantWithToolCallsNotResidue(self):
        """content 空但带 tool_calls：合法调用声明，不是空壳。"""
        assert isEmptyAssistantResidue(_tool_call_message()[0]) is False

    def testToolResultMessageNotResidue(self):
        """tool 结果消息（有 tool_call_id）不归本判定。"""
        msg = {"role": "tool", "tool_call_id": "c1", "content": ""}
        assert isEmptyAssistantResidue(msg) is False

    def testToolCallSourceChunkNotResidue(self):
        """TOOL_CALL 源归第一遍孤儿扫描管，本判定不越界。"""
        assert isEmptyAssistantResidue(_tool_chunk("", tool_call_id="c1")) is False

    def testUserEmptyContentNotResidue(self):
        """user 空消息不是 assistant 空壳（testNonAssistantUnaffected 的判定面）。"""
        assert isEmptyAssistantResidue(_conv_chunk("", role="user")) is False


class TestSweepResidues:
    def testEmptyAssistantResidueSwept(self):
        """空壳 assistant 被剔，正常 assistant（有 content）保留。"""
        view = [
            _conv_chunk("", turn_id="t1"),
            _conv_chunk("正常回复", turn_id="t1"),
        ]
        report = sweepResidues(view)
        assert [c.content for c in report.kept] == ["正常回复"]
        assert report.orphan_count == 1
        assert report.orphans[0].content == ""
        # 细分读数：本次被剔的全是空壳残留
        assert len(report.residues) == 1

    def testToolResultOrphanStillSwept(self):
        """既有孤儿判定不回退：pairs_with 指向不在视图的目标 → 剔。"""
        view = [
            _conv_chunk("user turn", role="user", turn_id="t1"),
            _tool_chunk("orphan result", pairs_with="t_missing"),
        ]
        report = sweepResidues(view)
        assert [c.content for c in report.kept] == ["user turn"]
        assert report.orphan_count == 1
        assert report.orphans[0].content == "orphan result"
        assert report.residues == []  # 本轮剔的是孤儿，不是空壳

    def testToolCallAssistantKept(self):
        """assistant content 空但有 tool_calls → 保留（合法调用声明）。"""
        msg = _tool_call_message()[0]
        report = sweepResidues([msg])
        assert report.orphan_count == 0
        assert len(report.kept) == 1 and report.kept[0] is msg

    def testNonAssistantUnaffected(self):
        """user 消息不受影响：有 content 的照常保留，空 content 的也不按空壳剔。"""
        view = [
            _conv_chunk("用户的问题", role="user", turn_id="t1"),
            _conv_chunk("", role="user", turn_id="t1"),
        ]
        report = sweepResidues(view)
        assert len(report.kept) == 2
        assert report.orphan_count == 0

    def testSweepTwiceIdempotent(self):
        """对已 sweep 的列表再 sweep 一次，结果不变。"""
        view = [
            _conv_chunk("", turn_id="t1"),
            _conv_chunk("keep me", turn_id="t1"),
            _tool_chunk("orphan", pairs_with="ghost"),
        ]
        once = sweepResidues(view)
        twice = sweepResidues(once.kept)
        assert [c.content for c in twice.kept] == [c.content for c in once.kept]
        assert twice.orphan_count == 0
        assert twice.residues == []

    def testPairedToolResultSurvivesSweep(self):
        """配对完整的工具结果不因第二遍清扫被误伤。"""
        view = [
            _conv_chunk("user turn", role="user", turn_id="t1"),
            _conv_chunk("final answer", turn_id="t1"),
            _tool_chunk("result", pairs_with="t1", tool_call_id="c1"),
        ]
        report = sweepResidues(view)
        assert report.orphan_count == 0
        assert len(report.kept) == 3

    def testValidatePairingSemanticsUnchanged(self):
        """第一遍既有语义不动：validate_pairing 不管空壳 assistant。"""
        report = validate_pairing([_conv_chunk("")])
        assert len(report.kept) == 1 and report.orphans == []

    def testKeptPreservesOriginalOrder(self):
        view = [
            _conv_chunk("a", turn_id="t1"),
            _conv_chunk("", turn_id="t1"),
            _conv_chunk("b", turn_id="t2"),
        ]
        report = sweepResidues(view)
        assert [c.content for c in report.kept] == ["a", "b"]

    def testEmptyView(self):
        report = sweepResidues([])
        assert report.kept == [] and report.orphans == [] and report.residues == []


class TestPoolDrawFiltersResidue:
    def testDrawFiltersResidue(self):
        """红测核心：draw 出口接入第二遍清扫后，空壳 assistant 不再泄入视图。

        构造参照 tests/unit/context/test_pairing.py 的真池方式：小预算池 +
        add_context 归档一条空壳 assistant 与一条正常消息。
        """
        from neurova.context_pool import ContextPool

        pool = ContextPool(user_id="u", agent_id="a", max_tokens=100)
        pool.add_context(_conv_chunk("正常消息", turn_id="t1", tokens=10))
        pool.add_context(_conv_chunk("", turn_id="t1", tokens=0))

        view = pool.draw()
        contents = [c.content for c in view]
        assert "" not in contents, f"空壳 assistant 泄入视图: {contents!r}"
        assert "正常消息" in contents

    def testDrawStillKeepsPairedToolCall(self):
        """清扫不误伤：配对完整的工具结果照常入视图。"""
        from neurova.context_pool import ContextPool

        pool = ContextPool(user_id="u", agent_id="a", max_tokens=100)
        pool.add_context(_conv_chunk("turn", role="user", turn_id="t1", tokens=20))
        pool.add_context(_tool_chunk("result", pairs_with="t1", tool_call_id="c1", tokens=10))

        view = pool.draw()
        assert any(c.source == ContextSource.TOOL_CALL for c in view)
        assert any(c.content == "result" for c in view)

    def testSearchFaceUnaffectedBySweep(self):
        """search 是主动召回工具面，不接第二遍清扫：正常条目照常可检索。"""
        from neurova.context_pool import ContextPool

        pool = ContextPool(user_id="u", agent_id="a", max_tokens=100)
        pool.add_context(_conv_chunk("unique needle content", turn_id="t1", tokens=10))
        pool.add_context(_conv_chunk("", turn_id="t1", tokens=0))

        hits = pool.search("unique needle", limit=8)
        assert any(c.content == "unique needle content" for c in hits)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
