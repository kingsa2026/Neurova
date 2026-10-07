"""SkillGLoW 对比落地(2026-10-07):整合召回预检 + 全自动 commit gate
+ 吸收账本迁移 + 计划仓溢出留痕。

治理决策(用户指令 2026-10-07;规则修订登记于
docs/08-research/skillglow_vs_neurova_skill_consolidation_2026-10-07.md §0):
整合审批引入全自动 commit gate 替代人工审批——确定性多检 fail-closed
(任一检不过仍留人工),治理开关 consolidation_auto_commit_enabled(默认开,
env NEUROVA_CONSOLIDATION_AUTO_COMMIT 逃生门),动作=归档可逆+账本迁移+全程留痕。
新技能生成类产物维持评审闸不变。
"""

import json

import pytest

from neurova.evolution.skill_consolidator import (
    ConsolidationPlanStore,
    auto_commit_gate_issues,
    maybe_auto_commit,
)


def _service_stub(umbrella_desc="统一 pdf_export 与 report_export 的文档导出工具族",
                  missing=()):
    """SkillService 替身:get_skill_info / archive_skill / 记账。

    umbrella 名叫 pdf_export_pro——名字与描述真实耦合(名述脱钩是预检
    要拦的真实缺陷,夹具不能自带这个缺陷)。
    """

    svc = type("Svc", (), {})()
    svc.skills_dir = None
    skills = {
        "umbrella_a": {"name": "pdf_export_pro", "description": umbrella_desc},
        "pdf_export": {"name": "pdf_export", "description": "导出 PDF"},
        "report_export": {"name": "report_export", "description": "导出报表"},
    }
    svc.archived = []

    def get_skill_info(skill_id):
        if skill_id in missing:
            return None
        return skills.get(skill_id)

    def archive_skill(skill_id):
        svc.archived.append(skill_id)
        return {"success": True}

    svc.get_skill_info = get_skill_info
    svc.archive_skill = archive_skill
    return svc


def _plan(umbrella="umbrella_a", absorbed=("pdf_export", "report_export"),
          basis="identity"):
    return {"umbrella": umbrella, "absorbed": list(absorbed), "status": "pending",
            "basis": basis, "reason": "测试簇"}


class _ExpStub:
    def __init__(self):
        self.migrated = []

    def migrate_records(self, src, dst):
        self.migrated.append((src, dst))
        return 2


@pytest.fixture
def exp_stub(monkeypatch):
    stub = _ExpStub()
    import neurova.evolution.skill_experience as se

    monkeypatch.setattr(se, "get_skill_experience_store", lambda: stub)
    yield stub


class TestPreflight:
    def test_passes_when_umbrella_covers_absorbed(self):
        issues = auto_commit_gate_issues(_service_stub(), _plan())
        assert issues == []

    def test_fails_when_description_disjoint(self):
        svc = _service_stub(umbrella_desc="完全无关的天气查询技能")
        issues = auto_commit_gate_issues(svc, _plan())
        assert issues, "umbrella 召不回被吸收成员 → 不得自动提交"
        # pdf_export 恰为伞名的子串会被召回；被拦的证据必须是 report_export
        # 召回失败与/或名述脱钩
        assert any("report_export" in i or "名述脱钩" in i for i in issues)

    def test_fails_when_umbrella_missing(self):
        svc = _service_stub(missing=("umbrella_a",))
        assert auto_commit_gate_issues(svc, _plan())

    def test_name_prefix_cluster_never_auto(self):
        svc = _service_stub()
        issues = auto_commit_gate_issues(svc, _plan(basis="name_prefix"))
        assert any("留人工" in i for i in issues)


class TestAutoCommit:
    def _seed_store(self, tmp_path, plan):
        store = ConsolidationPlanStore(tmp_path)
        store.upsert([plan])
        return store

    def test_gate_pass_executes_without_human(self, tmp_path, monkeypatch, exp_stub):
        monkeypatch.setenv("NEUROVA_CONSOLIDATION_AUTO_COMMIT", "1")
        svc = _service_stub()
        store = self._seed_store(tmp_path, _plan())

        audits = maybe_auto_commit(svc, store, store.load())

        assert svc.archived == ["pdf_export", "report_export"]
        entry = next(p for p in store.load() if p["umbrella"] == "umbrella_a")
        assert entry["status"] == "approved"
        assert entry["decided_by"] == "auto_commit_gate"
        assert entry["gate_issues"] == []
        assert audits and audits[0]["umbrella"] == "umbrella_a"
        assert exp_stub.migrated == [("pdf_export", "umbrella_a"),
                                     ("report_export", "umbrella_a")]

    def test_gate_fail_stays_pending_for_human(self, tmp_path, monkeypatch, exp_stub):
        monkeypatch.setenv("NEUROVA_CONSOLIDATION_AUTO_COMMIT", "1")
        svc = _service_stub(umbrella_desc="完全无关的天气查询技能")
        store = self._seed_store(tmp_path, _plan())

        maybe_auto_commit(svc, store, store.load())

        assert svc.archived == []
        entry = next(p for p in store.load() if p["umbrella"] == "umbrella_a")
        assert entry["status"] == "pending"
        assert entry["gate_issues"]
        assert exp_stub.migrated == []

    def test_flag_off_stays_pending(self, tmp_path, monkeypatch, exp_stub):
        monkeypatch.setenv("NEUROVA_CONSOLIDATION_AUTO_COMMIT", "0")
        svc = _service_stub()
        store = self._seed_store(tmp_path, _plan())

        maybe_auto_commit(svc, store, store.load())

        assert svc.archived == []
        assert next(p for p in store.load() if p["umbrella"] == "umbrella_a")["status"] == "pending"


class TestOverflowAccounting:
    def test_upsert_overflow_counted_not_silent(self, tmp_path):
        store = ConsolidationPlanStore(tmp_path)
        plans = [{"umbrella": f"u{i:03d}", "status": "pending"} for i in range(60)]
        items = store.upsert(plans)
        assert len(items) == 50
        assert store.overflow_dropped == 10, "工单 016 口径:溢出必须留痕计数"


class TestLedgerMigration:
    def test_migrate_records_moves_and_dedupes(self):
        from neurova.evolution.skill_experience import SkillExperienceStore

        store = SkillExperienceStore()
        # source=manual：被吸收技能的 applied 记录是已生效史（不走 C10 待审队列），
        # 迁移语义正是"重键已生效史"——用会进待审队列的来源反而测错对象
        store.record_experience(skill_id="old_skill", content="导出前先压缩图片",
                                source="manual", context="")
        store.record_experience(skill_id="old_skill", content="导出前先压缩图片",
                                source="manual", context="")
        moved = store.migrate_records("old_skill", "umbrella_a")
        assert moved == 1, "同内容去重"
        assert store.get_records("old_skill") == []
        assert [r.content for r in store.get_records("umbrella_a")] == ["导出前先压缩图片"]

    def test_migrate_from_empty_is_zero(self):
        from neurova.evolution.skill_experience import SkillExperienceStore

        store = SkillExperienceStore()
        assert store.migrate_records("ghost", "umbrella_a") == 0
