# -*- coding: utf-8 -*-
"""窗口预算组合口径审计钉（2026-09-14）。

get_token_budget_for_model = 模型窗口 ×0.6 视图安全系数（pool 侧契约，
test_dynamic_budget 钉死）；_resolve_window_token_budget 再取其 60% 作为
窗口份额。组合 ≈ 模型窗口 36%——kai 修复既定成本口径，本文件钉死防漂移。
"""
import pytest


class TestWindowBudgetComposition:
    def test_composed_share_of_window(self, monkeypatch):
        """组合口径：窗口预算 = clamp(池预算×0.6)，池预算=clamp(窗口×0.6)。"""
        from neurova.context_pool import ContextPool

        monkeypatch.setattr(
            ContextPool,
            "get_token_budget_for_model",
            staticmethod(lambda name, default_budget=16000: int(131072 * 0.6)),  # 78643
        )
        orch = _orchestrator()
        # 78643 × 0.6 = 47185（≈ 128k 窗口的 36%）
        assert orch._resolve_window_token_budget() == 47185

    def test_clamp_lower(self, monkeypatch):
        from neurova.context_pool import ContextPool

        monkeypatch.setattr(
            ContextPool, "get_token_budget_for_model",
            staticmethod(lambda name, default_budget=16000: 4915),  # 8k 窗口的 0.6
        )
        orch = _orchestrator()
        assert orch._resolve_window_token_budget() == 3000  # 下限钳

    def test_clamp_upper(self, monkeypatch):
        from neurova.context_pool import ContextPool

        monkeypatch.setattr(
            ContextPool, "get_token_budget_for_model",
            staticmethod(lambda name, default_budget=16000: 400000),  # 1M 窗口钳顶
        )
        orch = _orchestrator()
        assert orch._resolve_window_token_budget() == 100000  # 上限钳

    def test_explicit_override_wins(self):
        orch = _orchestrator()
        orch._window_token_budget = 5000
        assert orch._resolve_window_token_budget() == 5000

    def test_query_failure_falls_back(self, monkeypatch):
        from neurova.context_pool import ContextPool

        def _boom(*a, **k):
            raise RuntimeError("pool down")

        monkeypatch.setattr(ContextPool, "get_token_budget_for_model", staticmethod(_boom))
        orch = _orchestrator()
        # 回退 16000 × 0.6 = 9600
        assert orch._resolve_window_token_budget() == 9600


def _orchestrator():
    from unittest.mock import MagicMock

    from neurova.context.orchestrator import ContextOrchestrator

    agent = MagicMock()
    orch = ContextOrchestrator.__new__(ContextOrchestrator)
    orch._agent = agent
    return orch


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
