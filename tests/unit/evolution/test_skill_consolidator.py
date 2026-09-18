"""Wave 5 — 技能库巩固计划器测试。

纯计划产出(plan-only):识别窄技能簇、选 umbrella、**绝不改技能库**;
执行走既有评审闸。
"""

import pytest

from neurova.evolution.skill_consolidator import (
    SkillConsolidator,
    find_prefix_clusters,
)


class TestFindPrefixClusters:
    def test_groups_by_domain_prefix(self):
        clusters = find_prefix_clusters([
            "plugin-config-a", "plugin-config-b", "plugin-config-c", "unrelated",
        ])
        assert clusters == [["plugin-config-a", "plugin-config-b", "plugin-config-c"]]

    def test_min_size_filters_singletons(self):
        clusters = find_prefix_clusters(["a-x", "b-y"], min_size=2)
        assert clusters == []

    def test_sorted_by_size_desc(self):
        clusters = find_prefix_clusters([
            "p-a", "p-b", "q-a", "q-b", "q-c",
        ])
        assert clusters[0][0].startswith("q-")
        assert len(clusters[0]) == 3

    def test_empty_input(self):
        assert find_prefix_clusters([]) == []


class TestConsolidatorPlan:
    def test_plan_merges_cluster_into_umbrella(self):
        skills = {
            "deploy-helper-a": "部署辅助 A。", "deploy-helper-b": "部署辅助 B,内容更多更全。",
            "deploy-helper-c": "部署辅助 C。",
            "unrelated-skill": "无关技能。",
        }
        plans = SkillConsolidator().plan(skills)
        assert len(plans) == 1
        p = plans[0]
        assert p.umbrella == "deploy-helper-b"  # 正文最长者承载类级规则
        assert set(p.absorbed) == {"deploy-helper-a", "deploy-helper-c"}
        assert p.needs_reference_rehoming  # 包完整性:执行段须重新编目 references/
        assert "unrelated-skill" not in p.absorbed

    def test_plan_is_pure_no_mutation(self):
        skills = {"x-a": "A", "x-b": "B"}
        SkillConsolidator().plan(skills)
        assert skills == {"x-a": "A", "x-b": "B"}

    def test_empty_skills(self):
        assert SkillConsolidator().plan({}) == []

    def test_disjoint_clusters_produce_multiple_plans(self):
        skills = {
            "net-a": "网络 A", "net-b": "网络 B",
            "ui-a": "界面 A", "ui-b": "界面 B",
        }
        plans = SkillConsolidator().plan(skills)
        assert len(plans) == 2
        umbrellas = {p.umbrella for p in plans}
        assert len(umbrellas) == 2

    def test_plan_to_dict(self):
        plans = SkillConsolidator().plan({"k-a": "A", "k-b": "B"})
        d = plans[0].to_dict()
        # P1 收口：新增 basis/structure/intents——审批人必须能看出本簇依据
        # 哪一级身份聚出（真重复 vs 跨意图收编），合并风险完全不同。
        assert set(d) == {"umbrella", "absorbed", "reason", "needs_reference_rehoming",
                          "quality", "basis", "structure", "intents"}


# ── P1-2 接线：质量选取 / 落盘计划仓 / 审批执行 ──────────────────


from neurova.evolution.skill_consolidator import (  # noqa: E402
    ConsolidationApproval,
    ConsolidationPlanStore,
    _quality_of,
    plan_from_service,
)


class _FakeService:
    """最小技能库替身：list_skills/get_skill_info/get_skill_usage/archive_skill。"""

    def __init__(self, entries, usage=None, skills_dir="/tmp/nonexistent-consolidation"):
        self._entries = entries
        self._usage = usage or {}
        self.skills_dir = skills_dir
        self.archived = []

    def list_skills(self):
        return [{"id": sid, "name": sid, "description": desc} for sid, desc in self._entries.items()]

    def get_skill_info(self, sid):
        return {"id": sid, "description": self._entries.get(sid, "")}

    def get_skill_usage(self, sid):
        return self._usage.get(sid, {})

    def archive_skill(self, sid):
        self.archived.append(sid)
        return {"success": True}


def test_quality_prefers_successes_then_reuse():
    assert _quality_of({"usage": {"successes": 5}}) > _quality_of({"usage": {"successes": 1}})
    assert _quality_of({"funnel": {"applications": 3}}) > _quality_of({})
    assert _quality_of(None) == (0.0, 0.0, 0)


def test_plan_from_service_picks_quality_umbrella_not_longest_description():
    """umbrella 必须按质量账本选，而不是"描述最长"（旧行为）。"""
    entries = {
        "deploy-a": "很长的描述" * 20,
        "deploy-b": "短的",
        "deploy-c": "中等的描述",
    }
    # get_skill_usage 的真实形态：漏斗计数与 use_count/success_count 同层
    usage = {"deploy-b": {"success_count": 9, "applications": 9, "completions": 9}}
    plans = plan_from_service(_FakeService(entries, usage))
    assert len(plans) == 1
    assert plans[0].umbrella == "deploy-b", "成功观测最多者当选"
    assert set(plans[0].absorbed) == {"deploy-a", "deploy-c"}
    assert plans[0].quality  # 质量证据随计划落库，可审计


def test_plan_from_service_never_mutates_library():
    entries = {"x-a": "A", "x-b": "B"}
    service = _FakeService(entries)
    plan_from_service(service)
    assert service.archived == [], "计划段零副作用"


def test_plan_store_upsert_and_decide(tmp_path):
    store = ConsolidationPlanStore(tmp_path)
    store.upsert([{"umbrella": "u1", "absorbed": ["a"]}])
    store.upsert([{"umbrella": "u1", "absorbed": ["a", "b"]}])  # 同簇覆盖不叠加
    assert len(store.load()) == 1 and store.load()[0]["absorbed"] == ["a", "b"]
    assert store.decide("u1", approve=True) is True
    assert store.load()[0]["status"] == "approved"
    assert store.decide("u1", approve=True) is False, "已决计划不得重复决定"


def test_approval_archives_absorbed_and_keeps_umbrella(tmp_path):
    from neurova.evolution.skill_consolidator import ConsolidationPlan

    service = _FakeService({"k-a": "A", "k-b": "B"})
    store = ConsolidationPlanStore(tmp_path)
    plan = ConsolidationPlan(umbrella="k-b", absorbed=["k-a"], reason="r")
    store.upsert([plan.to_dict()])
    result = ConsolidationApproval(service, store).approve("k-b", ["k-a"])
    assert result["archived"] == ["k-a"] and result["failed"] == []
    assert service.archived == ["k-a"]
    assert "k-b" not in service.archived, "umbrella 保留为类级技能，绝不归档它"
    assert store.load()[0]["status"] == "approved"


def test_approval_partial_failure_keeps_plan_pending(tmp_path):
    class _Flaky(_FakeService):
        def archive_skill(self, sid):
            if sid == "bad":
                return {"success": False, "error": "boom"}
            return super().archive_skill(sid)

    service = _Flaky({"k-a": "A", "k-b": "B", "k-c": "C"})
    store = ConsolidationPlanStore(tmp_path)
    store.upsert([{"umbrella": "k-a", "absorbed": ["k-b", "bad"]}])
    result = ConsolidationApproval(service, store).approve("k-a", ["k-b", "bad"])
    assert result["archived"] == ["k-b"] and result["failed"] == ["bad"]
    assert store.load()[0]["status"] == "pending", "有失败则计划留待重试"
