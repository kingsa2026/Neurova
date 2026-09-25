"""E1 收口对账（工单 015，§9 E1 出口判据）。

前提修正：E1 阶段还没有生产写入方过咽喉（条目库降级在 019、切读在 011），
所以"新旧双写零差异"此刻无可对象。本票因此改为可实证的等价判据——
**预测 vs 实跑对账**：先用咽喉规则静态算出旧库会被折成多少条事实，
再把同一批数据真灌进一个一次性底座跑一遍，两者必须逐个主体完全一致。
对不上就说明"规则解释"与"规则执行"已经分叉，而这正是宽重构最危险的漂移。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import AdmissionRequest, KnowledgeAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.reconcile import FoundationReconciler
from neurova.knowledge.repository import KnowledgeRepository


@pytest.fixture
def legacy(tmp_path) -> KnowledgeRepository:
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    repo.create_knowledge("default", "同一篇笔记", "完全一样的正文内容", owner_user_id="u1")
    repo.create_knowledge("default", "又一篇笔记", "完全一样的正文内容", owner_user_id="u1")
    repo.create_knowledge("kai", "同一篇笔记", "完全一样的正文内容", owner_user_id="u1")
    repo.create_knowledge("default", "另一件事", "不同的正文", owner_user_id="u1")
    return repo


class TestReconcileAgainstRealData:
    def test_plan_reports_the_dedup_prediction(self, legacy):
        plan = FoundationReconciler.plan(legacy)

        assert plan["legacy_rows"] == 4
        # 去重按 agent 分域：default 的两条同内容折成 1 条，kai 那条属另一租户，不跨域折叠
        assert plan["predicted_facts"] == 3
        assert plan["redundant_rows"] == 1

    def test_prediction_matches_actual_replay_exactly(self, legacy, tmp_path):
        plan = FoundationReconciler.plan(legacy)

        report = FoundationReconciler.reconcile(legacy, str(tmp_path / "replay.db"))

        assert report["ok"] is True, report["diffs"]
        assert report["predicted"]["facts"] == report["actual"]["facts"] == 3
        assert report["predicted"]["subjects"] == report["actual"]["subjects"]
        assert report["diffs"] == []

    def test_extra_write_that_bypasses_rules_is_caught(self, legacy, tmp_path):
        """人为在回放库里塞一条不走咽喉的事实，对账必须报出来而不是继续"看起来一致"。"""
        replay = str(tmp_path / "replay.db")
        FoundationReconciler.reconcile(legacy, replay)
        stray = KnowledgeFactStore(replay)
        key = stray.upsertSubject("ghost", "幽灵主体")
        stray.upsertFact("ghost", key, "haunts", "东西", "没有断言也不该存在的事实")
        stray.close()

        report = FoundationReconciler.reconcile(legacy, replay)

        assert report["ok"] is False
        assert any("facts" in d for d in report["diffs"])

    def test_legacy_rows_are_never_mutated(self, legacy, tmp_path):
        before = sum(len(v) for v in legacy._items.values())

        FoundationReconciler.reconcile(legacy, str(tmp_path / "replay.db"))

        assert sum(len(v) for v in legacy._items.values()) == before
        assert legacy._conflicts == {}, "对账不得反过来污染旧账本"


class TestMigrationPlanShape:
    def test_plan_groups_are_actionable_for_ticket_019(self, legacy):
        plan = FoundationReconciler.plan(legacy)

        assert plan["groups"], "至少要有一组待折叠的重复"
        assert plan["per_agent_domains"] == 2
        group = plan["groups"][0]
        assert {"content_key", "count", "knowledge_ids"} <= set(group)
        assert group["count"] == 2 and len(group["knowledge_ids"]) == 2
