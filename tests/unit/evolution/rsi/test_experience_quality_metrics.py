"""008 · 经验质量成为可告警指标（红绿灯 TDD）。

没有度量面，002-007 的收紧在观测上仍不可证伪（看不见"变好了"）。本票钉四件事：

1. `EKB.quality_snapshot()` 是规范读数的唯一算式来源——形成条数 / `unevidenced`
   占比 / 命中率 / 平均采纳后成功率；
2. 形成侧第三态从 `tags=["unevidenced"]` 的字符串 hack 升成一等列
   `evidence_state`（002 留的前瞻，到这里才落地）；
3. 指标必须有**写入方**（`RSIOrchestrator` 每轮刷新）与被**读取方**
   （`RSIDashboard` 经验视图），定义了没人写 = 缺陷，写了没人读也是；
4. 空库不得被读成"100% 无证据"，无采纳决策不得被读成"成功率 0"——
   这两条反向锁正是本轮一路在防的"把没测到读成没出问题"的反向形态。
"""

from __future__ import annotations

import pytest

from neurova.evolution.rsi.metrics import AlertLevel, RSIMetrics
from neurova.skills.experience_knowledge_base import (
    ExperienceKnowledgeBase,
    ExperienceRecord,
)


def _rec(text: str, success: bool = True) -> ExperienceRecord:
    return ExperienceRecord(
        skill_name="chat",
        context={"user_input": text},
        result={"reply_excerpt": "r"},
        success=success,
    )


@pytest.fixture()
def ekb(tmp_path):
    db = ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb.db"))
    yield db
    db.close()


class TestQualitySnapshot:
    def test_empty_db_reads_as_no_data_not_full_of_doubt(self, ekb):
        snap = ekb.quality_snapshot()
        assert snap["rows"] == 0
        assert snap["unevidenced_ratio"] == 0.0, "空库不得被读成 100% 无证据"
        assert snap["adoption_decisions"] == 0
        assert snap["adoption_success_rate"] is None, "无采纳决策 ≠ 成功率 0"

    def test_formation_evidence_ratio(self, ekb):
        for i in range(2):
            ekb.add_experience_record("chat", _rec(f"任务 甲 {i}"), evidence=None)
        for i in range(2):
            ekb.add_experience_record("chat", _rec(f"任务 乙 {i}"), evidence=True)
        snap = ekb.quality_snapshot()
        assert snap["rows"] == 4
        assert snap["unevidenced_ratio"] == pytest.approx(0.5)

    def test_adoption_moves_the_success_rate(self, ekb):
        """验收 1：一条经验被采纳且该轮失败 ⇒ 平均采纳后成功率必须动。"""
        good = ekb.add_experience_record("chat", _rec("做成的一件事"), evidence=True)
        bad = ekb.add_experience_record("chat", _rec("做砸的一件事", success=False), evidence=False)
        ekb.record_injection_adoption([good], True)
        first = ekb.quality_snapshot()
        assert first["adoption_success_rate"] == pytest.approx(1.0)

        ekb.record_injection_adoption([bad], False)
        second = ekb.quality_snapshot()
        assert second["adoption_success_rate"] == pytest.approx(0.5)
        assert second["adoption_success_rate"] < first["adoption_success_rate"]

    def test_hit_rate_counts_injected_rows_only(self, ekb):
        a = ekb.add_experience_record("chat", _rec("被用过"), evidence=True)
        ekb.add_experience_record("chat", _rec("从没被用过"), evidence=True)
        assert ekb.quality_snapshot()["hit_rate"] == 0.0
        ekb.record_injection_adoption([a], True)
        assert ekb.quality_snapshot()["hit_rate"] == pytest.approx(0.5)

    def test_unevidenced_marker_is_a_column_not_a_tag_hack(self, ekb):
        rid = ekb.add_experience_record("chat", _rec("无回执的一轮"), evidence=None)
        row = ekb.get_experience_records(agent_id=None)[0]
        assert row["evidence_state"] == "unevidenced", "第三态必须是一等列"
        assert "unevidenced" not in (row.get("tags") or []), "tags 侧的字符串 hack 退役"
        assert rid == row["id"]


class TestAlerts:
    def test_all_unevidenced_library_alerts(self):
        m = RSIMetrics()
        m.record_metric(RSIMetrics.EXPERIENCE_ROWS, 9)
        m.record_metric(RSIMetrics.EXPERIENCE_UNEVIDENCED_RATIO, 1.0)
        fired = [a for a in m.check_alerts() if a.metric == RSIMetrics.EXPERIENCE_UNEVIDENCED_RATIO]
        assert fired and fired[0].level is AlertLevel.WARNING, "全库无证据必须可告警"

    def test_clean_library_does_not_alert(self):
        m = RSIMetrics()
        m.record_metric(RSIMetrics.EXPERIENCE_ROWS, 9)
        m.record_metric(RSIMetrics.EXPERIENCE_UNEVIDENCED_RATIO, 0.0)
        m.record_metric(RSIMetrics.EXPERIENCE_ADOPTION_SUCCESS_RATE, 0.9)
        assert not [a for a in m.check_alerts() if a.metric.startswith("experience_")]

    def test_adoption_majority_failure_alerts(self):
        m = RSIMetrics()
        m.record_metric(RSIMetrics.EXPERIENCE_ADOPTION_DECISIONS, 4)
        m.record_metric(RSIMetrics.EXPERIENCE_ADOPTION_SUCCESS_RATE, 0.25)
        fired = [
            a for a in m.check_alerts() if a.metric == RSIMetrics.EXPERIENCE_ADOPTION_SUCCESS_RATE
        ]
        assert fired, "采纳后多数失败必须告警"

    def test_no_decisions_does_not_alert_as_failure(self):
        m = RSIMetrics()
        m.record_metric(RSIMetrics.EXPERIENCE_ADOPTION_DECISIONS, 0)
        m.record_metric(RSIMetrics.EXPERIENCE_ADOPTION_SUCCESS_RATE, 0.0)
        assert not [
            a for a in m.check_alerts() if a.metric == RSIMetrics.EXPERIENCE_ADOPTION_SUCCESS_RATE
        ], "没有采纳决策就不是'全部失败'，不得凭空告警"


class TestWriterAndReaderExist:
    def test_orchestrator_refresh_writes_snapshot(self, tmp_path, monkeypatch, rsi_probe_factory):
        """指标必须有生产写入方：从登记表算 → 写进 RSIMetrics。"""
        db = ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb.db"))
        db.add_experience_record("chat", _rec("无回执"), evidence=None)
        db.add_experience_record("chat", _rec("有回执"), evidence=True)
        import neurova.skills.experience_knowledge_base as ekb_mod

        monkeypatch.setattr(ekb_mod, "get_experience_knowledge_base", lambda: db)
        try:
            probe = rsi_probe_factory()
            probe.orchestrator._refresh_experience_metrics()
            metrics = probe.orchestrator.metrics
            assert metrics.get_metric(RSIMetrics.EXPERIENCE_ROWS) == 2
            assert metrics.get_metric(RSIMetrics.EXPERIENCE_UNEVIDENCED_RATIO) == 0.5
        finally:
            db.close()

    def test_dashboard_shows_experience_view(self, tmp_path):
        from neurova.evolution.rsi.convergence_analyzer import ConvergenceAnalyzer
        from neurova.evolution.rsi.dashboard import RSIDashboard

        m = RSIMetrics()
        m.record_metric(RSIMetrics.EXPERIENCE_ROWS, 2)
        m.record_metric(RSIMetrics.EXPERIENCE_UNEVIDENCED_RATIO, 0.5)
        m.record_metric(RSIMetrics.EXPERIENCE_HIT_RATE, 0.0)
        m.record_metric(RSIMetrics.EXPERIENCE_ADOPTION_SUCCESS_RATE, 0.0)
        view = RSIDashboard(m, ConvergenceAnalyzer()).get_overview()
        assert view["experience"]["rows"] == 2
        assert view["experience"]["unevidenced_ratio"] == 0.5
        assert "alerts" in view
