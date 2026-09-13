"""Wave 1 — prompt_optimizer 判定双路径与后向兼容。

PromptEvalCase 新增 task_input/expected_behavior/scorer 后:
  - 有 rubric 的用例走 LLM judge
  - 无 rubric 的用例退回子串检查(历史调用面零破坏)
"""

import pytest

from neurova.skills.prompt_optimizer import PromptEvalCase, PromptEvalSet


class TestSubstringPathBackwardCompat:
    """历史调用面:只有 required_elements/forbidden_patterns 的用例必须仍工作。"""

    def test_required_elements_pass(self):
        s = PromptEvalSet([PromptEvalCase(case_id="c1", description="含角色",
                                          required_elements=["你是一名"])])
        score, details = s.score_prompt("你是一名严谨的助手。")
        assert score == pytest.approx(1.0)
        assert details[0]["passed"]

    def test_required_elements_fail(self):
        s = PromptEvalSet([PromptEvalCase(case_id="c1", description="含角色",
                                          required_elements=["你是一名"])])
        score, details = s.score_prompt("普通文本。")
        assert score == pytest.approx(0.0)
        assert not details[0]["passed"]

    def test_forbidden_pattern(self):
        s = PromptEvalSet([PromptEvalCase(case_id="c1", description="禁止模糊",
                                          forbidden_patterns=["尽量"])])
        score, _ = s.score_prompt("尽量做好。")
        assert score == pytest.approx(0.0)

    def test_max_length(self):
        s = PromptEvalSet([PromptEvalCase(case_id="c1", description="限长", max_length=5)])
        assert s.score_prompt("12345")[0] == pytest.approx(1.0)
        assert s.score_prompt("123456")[0] == pytest.approx(0.0)


class TestScorerFieldDefaults:
    def test_scorer_defaults_auto(self):
        c = PromptEvalCase(case_id="c", description="d")
        assert c.scorer == "auto"

    def test_rubric_fields_default_empty(self):
        c = PromptEvalCase(case_id="c", description="d")
        assert c.task_input == ""
        assert c.expected_behavior == ""

    def test_has_rubric_helper(self):
        assert not PromptEvalCase(case_id="c", description="d").has_rubric()
        assert PromptEvalCase(case_id="c", description="d", expected_behavior="rubric").has_rubric()

    def test_scorer_substring_forces_substring_even_with_rubric(self):
        """显式 scorer=substring 时不走 judge。"""
        c = PromptEvalCase(case_id="c", description="d", expected_behavior="rubric",
                           scorer="substring", required_elements=["x"])
        assert not c.wants_judge()
