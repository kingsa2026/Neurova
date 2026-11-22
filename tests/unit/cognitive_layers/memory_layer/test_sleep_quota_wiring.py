"""资源治理 P1-2：睡眠整理周期的每日配额接线。

run_sleep_cycle 入口先过每日原子配额；拒绝时返回与既有形状一致的
空结果信封（total_processed=0），不得进入整合/洞见/落盘链。
"""

from types import SimpleNamespace

from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation


class TestSleepQuotaWiring:
    def test_run_sleep_cycle_denied_when_quota_exhausted(self, monkeypatch):
        monkeypatch.setattr(
            "neurova.core.background_quota.acquireDailyQuota", lambda *a, **k: False
        )
        stub = SimpleNamespace()
        result = SleepConsolidation.run_sleep_cycle(stub, [], phase="deep_sleep")

        assert result.get("quota_denied") is True
        assert result.get("total_processed") == 0
        assert result.get("merged_count") == 0
        assert result.get("insights_generated", 0) == 0

    def test_run_sleep_cycle_denied_on_legacy_phase_too(self, monkeypatch):
        # 旧路径（phase=sleep，shutdown/过载包装）同样过闸——fail-closed 面一致
        monkeypatch.setattr(
            "neurova.core.background_quota.acquireDailyQuota", lambda *a, **k: False
        )
        stub = SimpleNamespace()
        result = SleepConsolidation.run_sleep_cycle(stub, [], phase="sleep")

        assert result.get("quota_denied") is True
        assert result.get("total_processed") == 0
