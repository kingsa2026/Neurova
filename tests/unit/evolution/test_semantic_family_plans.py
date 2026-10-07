"""P3 语义族第二计划源 — 红灯先行的契约测试(2026-10-07,SkillGLoW 对比)。

结构族(工具序列)仍是主判据且先产先占成员;语义源只对**未被结构计划认领**
的技能按名述嵌入余弦聚"同目的、异序列"族——这正是结构判据的盲区:
不同工具序列实现同一目的的语义同义重复,结构源永不聚簇。

风险口径:语义族 = 跨序列收编,风险高于结构族 → basis="semantic" 的计划
**永不自动提交**(auto_commit_gate_issues 拦),只进人工审批面。
零 LLM:嵌入来自本地 bge ONNX;引擎不可用 → 空列表诚实降级。
"""

import pytest

from neurova.evolution.skill_consolidator import (
    auto_commit_gate_issues,
    plan_from_semantics,
)

_VEC = {"pdf_export": [1.0, 0.0], "pdf_export_v2": [0.97, 0.242], "weather_check": [0.0, 1.0]}


class _FakeCache:
    """向量缓存替身:按预置表返回,缺席技能无向量。"""

    def __init__(self, table):
        self.table = table

    def vectors_for(self, skills):
        return {k: self.table[k] for k in skills if k in self.table}


def _service_stub():
    """三个技能:a 与 b 同目的但工具序列不同(结构源盲区),c 无关。"""

    svc = type("Svc", (), {})()
    svc.skills_dir = None
    svc.skills = {
        "pdf_export": {"name": "pdf_export", "description": "把网页导出为 PDF 报告"},
        "pdf_export_v2": {"name": "pdf_export_v2", "description": "把网页转存成 PDF 报告文件"},
        "weather_check": {"name": "weather_check", "description": "查询城市天气"},
    }
    svc.tool_sequences = {
        "pdf_export": ["read", "export"],
        "pdf_export_v2": ["convert", "export"],
        "weather_check": ["http_get"],
    }
    svc.get_skill_info_calls = []

    def get_skill_info(skill_id):
        svc.get_skill_info_calls.append(skill_id)
        return {"name": skill_id, "description": svc.skills[skill_id]["description"],
                "manifest": {"config": {"tool_sequence": svc.tool_sequences[skill_id]}}}

    def list_skills():
        return [{"id": sid, "description": meta["description"]}
                for sid, meta in svc.skills.items()]

    def get_skill_usage(skill_id):
        return {"funnel": {"completions": 2 if skill_id == "pdf_export" else 1}}

    svc.get_skill_info = get_skill_info
    svc.list_skills = list_skills
    svc.get_skill_usage = get_skill_usage
    return svc


def _sem_plan(svc, **kw):
    plans = plan_from_semantics(svc, vector_cache=_FakeCache(_VEC), **kw)
    assert len(plans) == 1, f"应聚出 1 个语义族,实得 {len(plans)}"
    return plans[0]


class TestSemanticClustering:
    def test_cross_sequence_family_clustered(self):
        """结构源盲区:不同工具序列、同目的 → 语义源聚出。"""
        plan = _sem_plan(_service_stub())
        assert plan.basis == "semantic"
        assert set(plan.absorbed) == {"pdf_export_v2"}
        assert plan.umbrella == "pdf_export"  # 质量账本选优(completions=2)
        assert "语义" in plan.reason and "留人工" in plan.reason

    def test_exclude_honored(self):
        """结构计划已认领的成员不参与语义聚簇(两源不抢同一成员)。"""
        plans = plan_from_semantics(_service_stub(), exclude={"pdf_export", "pdf_export_v2"},
                                    vector_cache=_FakeCache(_VEC))
        assert plans == []

    def test_threshold_respected(self):
        plans = plan_from_semantics(_service_stub(), vector_cache=_FakeCache(_VEC),
                                    threshold=0.99)
        assert plans == []

    def test_engine_unavailable_degrades_honestly(self):
        plans = plan_from_semantics(_service_stub(), vector_cache=_FakeCache({}))
        assert plans == [], "嵌入引擎不可用 → 诚实降级(结构源是常备路径)"


class TestGateNeverAuto:
    def test_semantic_plan_never_auto_commits(self):
        svc = _service_stub()
        plan = _sem_plan(svc).to_dict()
        issues = auto_commit_gate_issues(svc, plan)
        assert any("留人工" in i for i in issues), "跨序列收编必须留人工"


class TestFlag:
    def test_semantic_plans_flag(self, monkeypatch):
        from neurova.evolution.skill_consolidator import (
            consolidation_semantic_plans_enabled,
        )

        monkeypatch.setenv("NEUROVA_CONSOLIDATION_SEMANTIC_PLANS", "0")
        assert consolidation_semantic_plans_enabled() is False
        monkeypatch.setenv("NEUROVA_CONSOLIDATION_SEMANTIC_PLANS", "1")
        assert consolidation_semantic_plans_enabled() is True
        monkeypatch.delenv("NEUROVA_CONSOLIDATION_SEMANTIC_PLANS")
        assert consolidation_semantic_plans_enabled() is True  # 治理默认开
