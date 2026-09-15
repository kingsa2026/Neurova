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
        assert set(d) == {"umbrella", "absorbed", "reason", "needs_reference_rehoming"}
