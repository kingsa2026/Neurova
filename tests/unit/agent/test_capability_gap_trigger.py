"""T-03：自主造能力的入口从"用户措辞"改挂到"能力缺口"。

事故（2026-09-24 取证）：用户上传 `memory.db` 说"还有这个 你看看有什么信息可以
提炼"，三轮都没走自主创建。原因是入口挂在**用户措辞关键词**上
（`_check_nl_synthesis` 的 `action_keywords`：帮我/读取/写入/搜索/…），
事故三轮原话**零命中**；15MB 日志里 `主动技能获取|需要技能` 命中 0 次。

而真实存在的信号是"能力缺口"：附件抽不出文本（S1）、同轮工具连续失败（S2）、
能力检索零命中（S3）。本文件钉住：缺口驱动取代关键词驱动，且老行为真退役。

判据：把 S1 摘掉 ⇒ `.db` 场景回到"不合成"（反向锁）。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from neurova.agent.capability_gap import (
    GAP_ATTACHMENT_UNREADABLE,
    GAP_CATALOG_MISS,
    GAP_REPEATED_TOOL_FAILURE,
    clearCapabilityGap,
    detectCapabilityGap,
    noteAttachmentSignal,
    recordCapabilityGap,
)

_DB_ATTACHMENT = {
    "file_id": "file_db01",
    "filename": "memory.db",
    "file_type": "file",
    "mime_type": "application/octet-stream",
    "bytes": b"SQLite format 3\x00" + b"\x00" * 4080,
}
_TEXT_ATTACHMENT = {
    "file_id": "file_txt01",
    "filename": "note.txt",
    "file_type": "text",
    "mime_type": "text/plain",
}


@pytest.fixture(autouse=True)
def _clean_gap_store():
    clearCapabilityGap("session-gap-test")
    yield
    clearCapabilityGap("session-gap-test")


def _pipeline():
    from neurova.agent.chat_pipeline import ChatPipeline
    from neurova.skill_system import SkillRegistry

    synthesizer = SimpleNamespace(calls=[])
    synthesizer.synthesize = lambda **kwargs: (
        synthesizer.calls.append(kwargs) or SimpleNamespace(success=False)
    )
    registry = SkillRegistry()
    agent = SimpleNamespace(
        config=SimpleNamespace(agent_id="agent-gap-01"),
        tool_synthesizer=synthesizer,
        skill_manager=None,
        _skill_registry=registry,
    )
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline._agent = agent
    # 附件字节经唯一咽喉注入（与生产同形：`_read_attachment_bytes(file_id)`）
    pipeline._read_attachment_bytes = (
        lambda file_id: (_DB_ATTACHMENT["bytes"] if file_id == "file_db01" else b"hello world")
    )
    pipeline._register_synthesized_tool = lambda registry, tool: {"success": True}
    return pipeline, synthesizer


def _run_entry(pipeline, user_input, attachments=None):
    """走生产入口：附件注入步（S1 生产点）→ 缺口驱动入口。"""
    ctx = SimpleNamespace(
        user_input=user_input,
        session_id="session-gap-test",
        metadata={"attachments": attachments} if attachments else {},
    )
    if attachments:
        ctx.user_input, _ = pipeline._inject_attachments_into_input(ctx.user_input, attachments)
    asyncio.run(pipeline._check_nl_synthesis(ctx))
    return ctx


class TestSignalJudgement:
    def test_unreadableAttachment_producesGap(self):
        """S1 生产点：抽取面拿不到正文 ⇒ 缺口成立，且原因随信号带走。"""
        noteAttachmentSignal("memory.db", "file", "file_db01", "unsupported_format")
        verdict = detectCapabilityGap()
        assert verdict.hasGap is True
        assert GAP_ATTACHMENT_UNREADABLE in verdict.kinds
        assert verdict.details[GAP_ATTACHMENT_UNREADABLE][0]["status"] == "unsupported_format"

    def test_textAttachment_isNotGap(self):
        """反例：可抽取的附件在生产点根本不投信号（判据要咬合，不能恒真）。"""
        pipeline, _ = _pipeline()
        _run_entry(pipeline, "看看", [_TEXT_ATTACHMENT])
        assert detectCapabilityGap().hasGap is False

    def test_repeatedToolFailures_countAsGap(self):
        recordCapabilityGap(GAP_REPEATED_TOOL_FAILURE, {"tool": "run_code"}, "session-gap-test")
        recordCapabilityGap(GAP_REPEATED_TOOL_FAILURE, {"tool": "run_code"}, "session-gap-test")
        verdict = detectCapabilityGap()
        assert verdict.hasGap is True
        assert GAP_REPEATED_TOOL_FAILURE in verdict.kinds

    def test_singleFailure_isNotGap(self):
        recordCapabilityGap(GAP_REPEATED_TOOL_FAILURE, {"tool": "run_code"}, "session-gap-test")
        assert detectCapabilityGap().hasGap is False

    def test_zeroCatalogHit_countsAsGap(self):
        recordCapabilityGap(GAP_CATALOG_MISS, {"query": "sqlite 表结构"}, "session-gap-test")
        verdict = detectCapabilityGap()
        assert verdict.hasGap is True
        assert GAP_CATALOG_MISS in verdict.kinds

    def test_gapIsConsumedOnce(self):
        """一次性消费：缺口被读取后清零，否则下一轮会无据重放同一缺口。"""
        recordCapabilityGap(GAP_CATALOG_MISS, {"query": "x"}, "session-gap-test")
        assert detectCapabilityGap().hasGap is True
        assert detectCapabilityGap().hasGap is False


class TestEntryWiring:
    def test_dbAttachmentWithoutKeywords_opensSynthesis(self):
        """事故原话逐字（不含任何关键词）喂进去，缺口驱动必须命中。

        走**生产链路**：注入步真去抽 `memory.db`（抽不出）→ 投 S1 →
        入口读到缺口 → 触发合成回退。不为测试手工投信号。
        """
        pipeline, synthesizer = _pipeline()
        _run_entry(pipeline, "还有这个 你看看有什么信息可以提炼", [_DB_ATTACHMENT])
        assert synthesizer.calls, "缺口信号未驱动合成回退"

    def test_keywordOnlyUtterance_noLongerSynthesizes(self):
        """老行为退役证明：关键词命中但无缺口 ⇒ 不再无据触发。"""
        pipeline, synthesizer = _pipeline()
        _run_entry(pipeline, "帮我读取文件")
        assert not synthesizer.calls, "关键词表仍在参与判定（应已退役）"

    def test_keywordTable_isGone(self):
        """关键词表在 `_check_nl_synthesis` 中已不存在。"""
        import inspect

        from neurova.agent.chat_pipeline import ChatPipeline

        source = inspect.getsource(ChatPipeline._check_nl_synthesis)
        assert "action_keywords" not in source, "关键词表仍在入口里"

    def test_synthesisStillSkippedWhenNotWired(self):
        """既有短路保留：未装配合成器时不报错也不触发（D3）。"""
        pipeline, _ = _pipeline()
        pipeline._agent.tool_synthesizer = None
        ctx = _run_entry(pipeline, "看看", [_DB_ATTACHMENT])
        assert ctx is not None


class TestReverseLock:
    def test_removingAttachmentSignal_returnsToNoSynthesis(self, monkeypatch):
        """反向锁：把 S1 生产点摘掉 ⇒ `.db` 场景回到"不合成" ⇒ 上一条用例必红。"""
        from neurova.agent import capability_gap as _cg

        monkeypatch.setattr(_cg, "noteAttachmentSignal", lambda *a, **k: False)
        pipeline, synthesizer = _pipeline()
        _run_entry(pipeline, "还有这个 你看看有什么信息可以提炼", [_DB_ATTACHMENT])
        assert not synthesizer.calls, "反向锁不成立：缺口信号没被绕开"


class TestObservationReadback:
    """观测面必须"写 → 读"闭环（AGENTS §2 断点红线）。"""

    def test_gapMetrics_haveReadSide(self):
        from neurova.agent.capability_gap import gapMetricReadout
        from neurova.agent.gap_metric_channel import resetGapMetrics

        resetGapMetrics()
        recordCapabilityGap(GAP_CATALOG_MISS, {"query": "sqlite 表结构"})
        detectCapabilityGap()

        readout = gapMetricReadout()
        assert readout["total"] >= 1, f"缺口命中没有读侧读数：{readout}"
        assert readout["by_kind"].get(GAP_CATALOG_MISS, 0) >= 1

    def test_gapMetric_surfacesInRsiStatus(self):
        """读侧经 RSI 状态面可达（不是只挂在模块里没人取）。"""
        from neurova.agent.gap_metric_channel import resetGapMetrics

        resetGapMetrics()
        recordCapabilityGap(GAP_CATALOG_MISS, {"query": "x"})
        detectCapabilityGap()

        from neurova.evolution.rsi.metrics import create_rsi_metrics

        assert create_rsi_metrics() is not None  # 指标面可用
        from neurova.evolution.rsi.orchestrator import _readGapMetrics

        assert _readGapMetrics()["total"] >= 1, "状态面读不到缺口读数（只写不读）"

    def test_prometheusCounter_isBumped(self):
        """同一处写入同步进 Prometheus 计数（唯一指标面，不另起第二套）。"""
        from neurova.agent.gap_metric_channel import resetGapMetrics
        from neurova.core.metrics import get_metrics

        resetGapMetrics()
        before = get_metrics().capability_gap_total.labels(kind=GAP_CATALOG_MISS)._value.get()
        recordCapabilityGap(GAP_CATALOG_MISS, {"query": "x"})
        detectCapabilityGap()
        after = get_metrics().capability_gap_total.labels(kind=GAP_CATALOG_MISS)._value.get()
        assert after == before + 1, f"Prometheus 计数没跟上：{before} → {after}"


class TestToolFailureSignalWiring:
    def test_twoFailures_throughHook_openGap(self):
        """S2 经**生产钩子**投递（不是测试手工投）。"""
        from neurova.agent.capability_gap import clearCapabilityGap, detectCapabilityGap
        from neurova.tool_executor import ToolExecutor

        clearCapabilityGap("s2")
        agent = SimpleNamespace(tool_memory=None, tool_lifecycle=None)
        executor = ToolExecutor.__new__(ToolExecutor)
        executor._agent = agent

        executor.on_tool_executed("run_code", {}, "跑一下", False, "builtin", 0.1)
        assert detectCapabilityGap().hasGap is False, "单次失败不该构成缺口"
        executor.on_tool_executed("run_code", {}, "跑一下", False, "builtin", 0.1)
        verdict = detectCapabilityGap()
        assert verdict.hasGap is True
        assert GAP_REPEATED_TOOL_FAILURE in verdict.kinds

    def test_successResetsStreak(self):
        from neurova.agent.capability_gap import clearCapabilityGap, detectCapabilityGap
        from neurova.tool_executor import ToolExecutor

        clearCapabilityGap("s2")
        agent = SimpleNamespace(tool_memory=None, tool_lifecycle=None)
        executor = ToolExecutor.__new__(ToolExecutor)
        executor._agent = agent

        executor.on_tool_executed("a", {}, "x", False, "builtin", 0.1)
        executor.on_tool_executed("b", {}, "x", True, "builtin", 0.1)
        executor.on_tool_executed("c", {}, "x", False, "builtin", 0.1)
        assert detectCapabilityGap().hasGap is False, "隔一次成功再失败不算连续"

    def test_policyDenial_isNotGap(self):
        """策略拒绝是决策不是故障（与断点 B 同口径，沿用既有判据）。"""
        from neurova.agent.capability_gap import clearCapabilityGap, detectCapabilityGap
        from neurova.tool_executor import ToolExecutor

        clearCapabilityGap("s2")
        agent = SimpleNamespace(tool_memory=None, tool_lifecycle=None)
        executor = ToolExecutor.__new__(ToolExecutor)
        executor._agent = agent
        # 拒绝形态取自单源判据 `security.governance.is_policy_denial` 识别的键，
        # 不在这里自造一个 `policy_denial` 键（那是第二份判据）。
        denial = {"success": False, "error": "策略拒绝：需审批", "pending_approval": {"reason": "shell 高危"}}

        executor.on_tool_executed("computer_shell", {}, "x", False, "builtin", 0.1, denial)
        executor.on_tool_executed("computer_shell", {}, "x", False, "builtin", 0.1, denial)
        assert detectCapabilityGap().hasGap is False


class TestCatalogMissSignalWiring:
    def test_zeroHitSearch_recordsGap(self):
        from neurova.agent.capability_gap import clearCapabilityGap, detectCapabilityGap
        from neurova.context import tool_search

        clearCapabilityGap("s3")
        tool_search.handle_control_tool("tool_search", {"query": "zzzz 不存在的查询"})
        verdict = detectCapabilityGap()
        assert verdict.hasGap is True
        assert GAP_CATALOG_MISS in verdict.kinds
