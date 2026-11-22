"""资源治理 P1-2：RSI 迭代的每日配额接线。

run_iteration 入口先过每日原子配额；拒绝时返回 quota_denied 信封，
不得进入迭代主体（反馈收集/寻优/应用一律不发生）。
"""

from types import SimpleNamespace

from neurova.evolution.rsi.orchestrator import RSIOrchestrator


class TestRSIQuotaWiring:
    def test_run_iteration_denied_when_quota_exhausted(self, monkeypatch):
        monkeypatch.setattr(
            "neurova.core.background_quota.acquireDailyQuota", lambda *a, **k: False
        )
        probe = {"hit": False}

        def _boom():
            probe["hit"] = True
            return []

        stub = SimpleNamespace(collect_feedback_signals=_boom)
        result = RSIOrchestrator.run_iteration(stub)

        assert result.get("quota_denied") is True
        assert result.get("applied_count") == 0
        assert probe["hit"] is False

    def test_run_iteration_allowed_when_quota_granted(self, monkeypatch):
        monkeypatch.setattr(
            "neurova.core.background_quota.acquireDailyQuota", lambda *a, **k: True
        )
        probe = {"hit": False}

        def _collect():
            probe["hit"] = True
            return []

        stub = SimpleNamespace(collect_feedback_signals=_collect)
        try:
            RSIOrchestrator.run_iteration(stub)
        except AttributeError:
            # 配额放行后进入迭代主体；stub 未实现后续协作对象，属预期边界
            pass
        assert probe["hit"] is True
