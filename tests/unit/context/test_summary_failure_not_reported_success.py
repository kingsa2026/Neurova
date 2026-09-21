# -*- coding: utf-8 -*-
"""P1-2 摘要失败不得被上层当成"新摘要成功"，据此谎报覆盖。

根因（三链路审计 P1-2）：契约错位。
`SummarizingCompressor.summarize` 在 LLM 超时/异常/幻觉未过时
`return previous_summary or None` —— 对池侧 `rollup_overflow_digest` 是合理的幂等
no-op，但对**窗口折叠层**，返回值非空即被 `window_compactor` 判为"本轮摘要成功"
（不再重试），并被 `orchestrator._apply_window_budget` 用来推进 `last_count` 与
覆盖 `cache["summary"]`。

实测（本文件红灯即证）：LLM 首轮成功、次轮抛错 → `摘要文本未变`、
`last_count 10→20`。即新增 10 条被记为"已被摘要覆盖"，而那份摘要诞生时它们
还在窗口里。影响：后续 `_DELTA_RESUMMARY_MSGS` 防抖期内不再触发摘要，被折叠
内容只在视图里留下一个与它无关的旧摘要标题——"零丢失"在归档层成立，但在
**摘要层是假账**。

契约（修复后）：
- 沿用旧摘要（`round_summary == previous_summary`）不算"本轮摘要成功"；
  `compact_window` 以 `summary_is_fresh` 显式暴露该事实，折叠层据此**不推进**
  覆盖记账；
- 判据落在**消费方可见的折叠结果**上（而非摘要器内部状态），因此对任何
  `summarize` 实现都成立——包括调用方自注入的桥（审计 §8 明禁"绕过生产装配点"）。

防回归纪律：禁止用 MagicMock 冒充 llm_call，失败通道用真实异常注入。
"""

import pytest

from neurova.context.summarizing_compressor import SummarizingCompressor
from neurova.context_pool import ContextInput, ContextSource


def _chunks(n: int, prefix: str = "消息"):
    return [
        ContextInput(
            source=ContextSource.CONVERSATION,
            content=f"{prefix}{i}：这是一段足够长的历史内容用于摘要",
            priority=60,
            metadata={"role": "user"},
        )
        for i in range(n)
    ]


class TestSummarizeKeepsIdempotentContract:
    """返回值契约不动：失败沿用旧摘要（池侧依赖这一 no-op 语义）。"""

    @pytest.mark.asyncio
    async def test_llm_error_reuses_previous_summary_verbatim(self):
        calls = {"n": 0}

        async def flaky_llm(prompt: str) -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                return "第一轮摘要：用户讨论了部署计划"
            raise RuntimeError("模拟 LLM 次轮失败")

        comp = SummarizingCompressor(llm_call=flaky_llm)
        first = await comp.summarize(_chunks(10), previous_summary="")
        assert "第一轮摘要" in first
        second = await comp.summarize(_chunks(10), previous_summary=first)
        assert second == first, "失败时应沿用旧摘要（不改动内容）"

    @pytest.mark.asyncio
    async def test_first_call_failure_without_previous_summary_returns_empty(self):
        async def failing_llm(prompt: str) -> str:
            raise RuntimeError("始终失败")

        comp = SummarizingCompressor(llm_call=failing_llm)
        assert await comp.summarize(_chunks(10), previous_summary="") in (None, "")


class TestFoldingSignalsFreshnessOfSummary:
    """折叠结果必须显式区分"新摘要"与"沿用旧摘要"。"""

    @pytest.mark.asyncio
    async def test_reused_summary_is_not_marked_fresh(self):
        from neurova.context.window_compactor import compact_window

        msgs = [{"role": "user", "content": "内容" * 200} for _ in range(12)]

        async def reuse_previous(dropped, previous_summary=""):
            return previous_summary  # 失败沿用旧摘要（非空）

        result = await compact_window(
            msgs, 300, summarize=reuse_previous, previous_summary="旧摘要"
        )
        assert result is not None
        assert result.summary == "旧摘要"
        assert result.summary_is_fresh is False, (
            "沿用旧摘要被标记为新鲜——折叠层据此推进覆盖记账，"
            "新增消息会被谎报为'已被摘要覆盖'"
        )

    @pytest.mark.asyncio
    async def test_new_summary_is_marked_fresh(self):
        from neurova.context.window_compactor import compact_window

        msgs = [{"role": "user", "content": "内容" * 200} for _ in range(12)]

        async def produce_new(dropped, previous_summary=""):
            return "本轮新摘要"

        result = await compact_window(
            msgs, 300, summarize=produce_new, previous_summary="旧摘要"
        )
        assert result is not None
        assert result.summary == "本轮新摘要"
        assert result.summary_is_fresh is True

    @pytest.mark.asyncio
    async def test_first_summary_without_previous_is_fresh(self):
        from neurova.context.window_compactor import compact_window

        msgs = [{"role": "user", "content": "内容" * 200} for _ in range(12)]

        async def produce_new(dropped, previous_summary=""):
            return "首轮摘要"

        result = await compact_window(msgs, 300, summarize=produce_new)
        assert result is not None and result.summary_is_fresh is True


class TestFoldingDoesNotAdvanceCoverageOnFailure:
    """折叠层：沿用旧摘要不得推进覆盖记账（否则新增消息被谎报已覆盖）。"""

    @pytest.mark.asyncio
    async def test_coverage_not_advanced_when_summary_reused(self):
        from unittest.mock import MagicMock

        from neurova.context.orchestrator import ContextOrchestrator

        agent = MagicMock()
        agent.config = MagicMock()
        agent.config.name = "t"
        agent.config.constitution = ""
        agent.config.behavior_rules = []
        agent.config.llm_model = "test-model"
        agent.memory_manager = MagicMock()
        agent.context_builder = MagicMock()
        agent.tool_router = None
        agent._skill_registry = None
        agent.soul = "s"
        agent.personality = ""
        agent.conversation_history = []
        agent.growth_log_manager = MagicMock()
        agent.user_id = "u1"
        agent.agent_id = "a1"

        orch = ContextOrchestrator(agent, use_pool=True)
        orch.auto_compact_enabled = True
        orch._window_token_budget = 600

        calls = {"n": 0}

        async def flaky_summarize(dropped, previous_summary=""):
            calls["n"] += 1
            if calls["n"] == 1:
                return "第一轮摘要"
            return previous_summary  # 失败沿用旧摘要（非空）

        orch._window_summarizer = flaky_summarize

        first = [{"role": "user", "content": f"第一轮第{i}条：" + "内容" * 60} for i in range(10)]
        await orch._apply_window_budget(first, 600, cache_key="room:x")
        slot = orch._window_compaction_cache["room:x"]
        first_count = slot["last_count"]

        second = first + [
            {"role": "user", "content": f"第二轮第{i}条：" + "内容" * 60} for i in range(10)
        ]
        # 超过防抖阈值，必然重调摘要
        await orch._apply_window_budget(second, 600, cache_key="room:x")
        slot = orch._window_compaction_cache["room:x"]

        assert calls["n"] >= 2, "未触发第二轮摘要（本用例前提）"
        assert slot["last_count"] == first_count, (
            f"摘要失败却推进了覆盖记账：last_count {first_count} → {slot['last_count']}"
            "——新增消息被谎报为'已被摘要覆盖'"
        )
        assert slot["summary"] == "第一轮摘要", "摘要内容被非新摘要覆盖"
