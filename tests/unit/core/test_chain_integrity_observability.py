"""010/006 残留 · 只写不读的计数必须接线到既有观测面。

票据 010 要求「a 的出声 + 一个**可读计数**（观测面走既有状态面，不新开端点）」；
票据 006 要求同名冲突「**计数并可观测**」。前一轮两个计数器都落了地，但：
`creation_governance.missing_context_count()` 在 `neurova/` 内**零生产消费方**
（只有测试读它），`SkillRegistry._name_collision_count` 只被日志用过一次——
即"写出了读数，没有任何人读"，正是协作红线里点名的断点形态。

既有状态面是 `/metrics`（Prometheus，见 `core/metrics.py` 与
`api/app.py::_register_metrics_endpoint`）。本文件钉三件事：

1. 两个读数在 `/metrics` 文本里各有一个具名序列；
2. 抓取时刷新（与池/缓存 gauge 同款"抓取时快照"，不是常驻埋点也不新开端点）；
3. 数值来自**单一事实源**（计数器本体），不重算、不复制一份平行账。
"""

from __future__ import annotations

import pytest

prometheus_client = pytest.importorskip("prometheus_client")

from neurova.core.metrics import get_metrics, generate_metrics_text  # noqa: E402

MISSING_METRIC = "neurova_ticket_context_missing"
COLLISION_METRIC = "neurova_skill_name_collisions"


class TestMissingContextCounterIsReadable:
    def test_scrape_reports_the_counter(self, monkeypatch):
        from neurova.skills import creation_governance

        monkeypatch.setattr(creation_governance, "_missing_context_counter",
                            creation_governance.missing_context_count() + 7)
        get_metrics().observe_chain_integrity()
        text = generate_metrics_text()
        assert MISSING_METRIC in text, (
            "票据上下文缺失计数没有接线到 /metrics：写出去了没人读"
        )

    def test_value_comes_from_the_single_source(self, monkeypatch):
        from neurova.skills import creation_governance

        before = creation_governance.missing_context_count()
        monkeypatch.setattr(creation_governance, "_missing_context_counter", before + 3)
        get_metrics().observe_chain_integrity()
        value = _gauge_value(MISSING_METRIC)
        assert value == float(before + 3), (
            f"读数不是来自计数器本体（期望 {before + 3}，得到 {value}）"
        )


class TestNameCollisionCounterIsReadable:
    def test_scrape_reports_the_counter(self, monkeypatch):
        import neurova.skill_system as skill_system

        monkeypatch.setattr(skill_system, "registered_collision_count", lambda: 4)
        get_metrics().observe_chain_integrity()
        assert _gauge_value(COLLISION_METRIC) == 4.0, (
            "同名覆盖计数没有接线到 /metrics（006 要求计数并可观测）"
        )

    def test_no_registry_means_no_lazy_creation(self):
        """抓指标绝不懒建：尚未装配注册表 ⇒ 读数 0，不得顺手建一个。"""
        from neurova import skill_system

        standalone = skill_system.__getattr__("registered_collision_count")
        module = __import__("sys").modules["neurova.skill_system_module_standalone"]
        original = module._skill_registry_singleton
        module._skill_registry_singleton = None
        try:
            assert standalone() == 0
            get_metrics().observe_chain_integrity()
            assert module._skill_registry_singleton is None, "抓指标懒建了技能注册表"
        finally:
            module._skill_registry_singleton = original


class TestScrapeWiring:
    def test_metrics_endpoint_refreshes_chain_integrity(self):
        """接线点必须落在既有端点内，且与池/缓存同款抓取时刷新。"""
        from pathlib import Path

        src = Path("neurova/api/app.py").read_text(encoding="utf-8")
        assert "observe_chain_integrity()" in src, (
            "/metrics 端点没有刷新链路完整性读数（只挂 claim 不刷新）"
        )


def _gauge_value(name: str) -> float:
    from prometheus_client import REGISTRY

    for metric in REGISTRY.collect():
        if metric.name == name:
            for sample in metric.samples:
                if sample.name == name:
                    return float(sample.value)
    raise AssertionError(f"指标 {name} 未注册")
