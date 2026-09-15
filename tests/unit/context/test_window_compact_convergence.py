# -*- coding: utf-8 -*-
"""P0-2 窗口压缩收敛保证 + auto_compact_enabled 开关 + 90% 硬顶。

- 压缩摘要生成失败 → 从折叠区丢最旧一条重试（上限 3 次），压缩自身必须收敛
- auto_compact_enabled=False 时窗口超预算也原样返回（显式关闭语义）
- 硬顶：有效预算 = min(窗口预算, 模型上下文窗口×90%)——配置再大也不越过
"""
import pytest


class _FailingThenOkSummarizer:
    """前 fail_times 次调用返回 None（模拟摘要 LLM 失败），之后成功。"""

    def __init__(self, fail_times=1):
        self.fail_times = fail_times
        self.calls: list = []

    async def __call__(self, dropped_msgs, previous_summary=""):
        self.calls.append([m.get("content", "") for m in dropped_msgs])
        if len(self.calls) <= self.fail_times:
            return None
        return "摘要：" + "；".join(self.calls[-1])[:50]


class TestCompactWindowConvergence:
    @pytest.mark.asyncio
    async def test_summary_failure_retries_without_oldest(self):
        """摘要失败 → 丢最旧一条重试，最终产出摘要（收敛而非静态桩）。"""
        from neurova.context.window_compactor import compact_window

        # 中文密文：词级估算器对连续 ASCII 弱计数，CJK 才有真实体量
        msgs = [
            {"role": "user", "content": f"第{i}条消息：" + "重要内容" * 60}
            for i in range(12)
        ]
        summ = _FailingThenOkSummarizer(fail_times=1)
        compaction = await compact_window(
            msgs, budget_tokens=300, summarize=summ, keep_min_messages=2
        )
        assert compaction is not None
        assert compaction.summary  # 重试后拿到真摘要
        assert len(summ.calls) >= 2
        # 重试输入严格变短（丢最旧）
        assert len(summ.calls[1]) < len(summ.calls[0])
        # 丢掉的前缀在摘要行里显式标注（不静默消失）
        window_text = "\n".join(m.get("content", "") for m in compaction.window)
        assert "丢弃" in window_text or "最早" in window_text

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_falls_back_to_stub(self):
        """重试耗尽仍失败 → summary=None（编排层注入静态桩，既有语义）。"""
        from neurova.context.window_compactor import compact_window

        msgs = [
            {"role": "user", "content": f"第{i}条：" + "内容" * 60} for i in range(10)
        ]
        compaction = await compact_window(
            msgs, budget_tokens=300, summarize=_FailingThenOkSummarizer(fail_times=99),
            keep_min_messages=2,
        )
        assert compaction is not None
        assert compaction.summary is None
        assert compaction.compacted_count > 0

    @pytest.mark.asyncio
    async def test_under_budget_never_retries(self):
        """未超预算零行为变化（不调摘要器）。"""
        from neurova.context.window_compactor import compact_window

        summ = _FailingThenOkSummarizer(fail_times=99)
        msgs = [{"role": "user", "content": "tiny"}]
        assert await compact_window(msgs, 10000, summarize=summ) is None
        assert summ.calls == []


class TestOrchestratorAutoCompactSwitch:
    def _build_orchestrator(self):
        from unittest.mock import MagicMock

        from neurova.context.orchestrator import ContextOrchestrator

        agent = MagicMock()
        agent.config.workspace_path = ""
        agent.config.constitution = ""
        agent.config.behavior_rules = []
        agent.soul = "s"
        agent.personality = ""
        orch = ContextOrchestrator.__new__(ContextOrchestrator)
        orch._agent = agent
        # config/soul/personality/session_id 均为只读 property（委托 _agent/_session_id）
        orch._session_id = "s-test"
        orch._window_summarizer = None
        orch._window_compaction_cache = {}
        orch._last_folded_hashes = set()
        orch._DELTA_RESUMMARY_MSGS = 4
        return orch

    @pytest.mark.asyncio
    async def test_disabled_returns_msgs_unchanged(self):
        """auto_compact_enabled=False：超预算也原样返回。"""
        orch = self._build_orchestrator()
        orch.auto_compact_enabled = False
        msgs = [{"role": "user", "content": "超预算内容" * 500}] * 10
        out = await orch._apply_window_budget(list(msgs), budget_tokens=100)
        assert out == msgs

    @pytest.mark.asyncio
    async def test_enabled_folds_when_over_budget(self):
        orch = self._build_orchestrator()
        orch.auto_compact_enabled = True
        orch._window_token_budget = 100
        msgs = [{"role": "user", "content": "超预算内容" * 200} for _ in range(8)]
        out = await orch._apply_window_budget(list(msgs), budget_tokens=100)
        assert len(out) < len(msgs)

    @pytest.mark.asyncio
    async def test_hard_limit_caps_budget(self):
        """硬顶生效：窗口预算再大也不越过 _window_hard_limit。"""
        orch = self._build_orchestrator()
        orch.auto_compact_enabled = True
        orch._window_token_budget = 100000  # 名义预算巨大
        orch._window_hard_limit = 100       # 硬顶 100
        msgs = [{"role": "user", "content": "超预算内容" * 200} for _ in range(8)]
        out = await orch._apply_window_budget(list(msgs), budget_tokens=100000)
        assert len(out) < len(msgs)  # 硬顶触发折叠

    @pytest.mark.asyncio
    async def test_default_enabled(self):
        """默认开启（存量行为不回退）。"""
        orch = self._build_orchestrator()
        assert getattr(orch, "auto_compact_enabled", False) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
