"""Wave 2 — 约束闸测试。

逆反任一即丢弃变体。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.constraints import ConstraintValidator


@pytest.fixture
def validator():
    return ConstraintValidator(EvolutionConfig())


class TestSizeLimit:
    def test_skill_within_limit(self, validator):
        results = validator.validate("x" * 100, "skill")
        assert next(r for r in results if r.name == "size_limit").passed

    def test_skill_over_limit(self, validator):
        cfg = EvolutionConfig(max_skill_size=100)
        v = ConstraintValidator(cfg)
        r = next(r for r in v.validate("x" * 101, "skill") if r.name == "size_limit")
        assert not r.passed

    def test_exactly_at_limit_passes(self, validator):
        cfg = EvolutionConfig(max_skill_size=100)
        v = ConstraintValidator(cfg)
        r = next(r for r in v.validate("x" * 100, "skill") if r.name == "size_limit")
        assert r.passed

    def test_tool_description_limit(self):
        v = ConstraintValidator(EvolutionConfig(max_tool_desc_size=500))
        assert next(r for r in v.validate("x" * 500, "tool_description") if r.name == "size_limit").passed
        assert not next(r for r in v.validate("x" * 501, "tool_description") if r.name == "size_limit").passed

    def test_param_description_limit(self):
        v = ConstraintValidator(EvolutionConfig(max_param_desc_size=200))
        assert not next(r for r in v.validate("x" * 201, "param_description") if r.name == "size_limit").passed


class TestGrowthLimit:
    def test_within_growth(self, validator):
        cfg = EvolutionConfig(max_prompt_growth=0.2)
        v = ConstraintValidator(cfg)
        r = next(r for r in v.validate("x" * 110, "skill", baseline_text="x" * 100) if r.name == "growth_limit")
        assert r.passed

    def test_exceeds_growth(self):
        v = ConstraintValidator(EvolutionConfig(max_prompt_growth=0.2))
        r = next(r for r in v.validate("x" * 130, "skill", baseline_text="x" * 100) if r.name == "growth_limit")
        assert not r.passed

    def test_no_baseline_skips_growth(self, validator):
        results = validator.validate("x" * 100, "skill")
        assert not any(r.name == "growth_limit" for r in results)


class TestNonEmptyAndStructure:
    def test_empty_rejected(self, validator):
        r = next(r for r in validator.validate("   ", "skill") if r.name == "non_empty")
        assert not r.passed

    def test_skill_missing_frontmatter(self, validator):
        r = next(r for r in validator.validate("# 只有正文", "skill") if r.name == "skill_structure")
        assert not r.passed

    def test_skill_valid_frontmatter(self, validator):
        text = "---\nname: my-skill\ndescription: does a thing.\n---\n\n# Body"
        r = next(r for r in validator.validate(text, "skill") if r.name == "skill_structure")
        assert r.passed


class TestSemanticGate:
    def test_paraphrase_passes(self):
        v = ConstraintValidator(EvolutionConfig(semantic_similarity_threshold=0.5))
        base = "搜索 arXiv 论文,按关键词、作者或 ID。"
        evolved = "按关键词、作者或 ID 搜索 arXiv 论文。"
        r = next(r for r in v.validate(evolved, "skill", baseline_text=base) if r.name == "semantic_similarity")
        assert r.passed

    def test_topic_drift_rejected(self):
        v = ConstraintValidator(EvolutionConfig(semantic_similarity_threshold=0.9))
        base = "搜索 arXiv 论文,按关键词、作者或 ID。"
        evolved = "发送电子邮件给团队成员并管理日历日程安排。"
        r = next(r for r in v.validate(evolved, "skill", baseline_text=base) if r.name == "semantic_similarity")
        assert not r.passed

    def test_no_baseline_skips_semantic(self, validator):
        results = validator.validate("x" * 100, "skill")
        assert not any(r.name == "semantic_similarity" for r in results)


class TestValidateAllAggregation:
    def test_all_pass_helper(self, validator):
        text = "---\nname: s\ndescription: d.\n---\n\n# Body " + "x" * 50
        assert validator.all_pass(validator.validate(text, "skill"))

    def test_all_pass_false_on_any_failure(self, validator):
        assert not validator.all_pass(validator.validate("", "skill"))
