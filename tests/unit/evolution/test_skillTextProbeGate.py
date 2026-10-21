"""旧自动提交流程已退役：`apply_improvement` 只记修订/经验，不写技能正文。

正文写入的唯一路径是 `SkillEvolutionService.decide`（过门 + 审批/自动开关）；
本文件钉住“自动字典提案不得偷偷改正文”，防止第三条路径复活。
"""

from types import SimpleNamespace

import pytest

from neurova.evolution.skill_improver import (
    ImprovementType,
    SkillImprovement,
    get_skill_improver,
    reset_skill_improver,
)


def _skill_registry_with(context_template: str):
    skill = SimpleNamespace(
        name="sk",
        description="desc",
        version="1.0.0",
        config={"context_template": context_template},
    )
    registry = SimpleNamespace(get_skill=lambda sid: skill if sid == "sk" else None)
    return skill, registry


def _proposal() -> SkillImprovement:
    return SkillImprovement(
        improvement_id="imp-sk",
        skill_id="sk",
        improvement_type=ImprovementType.ERROR_HANDLING,
        description="字典建议",
        changes={"improved_text": "不应被自动写入的正文"},
        reason="真实失败",
    )


def test_apply_improvement_never_writes_text(monkeypatch):
    reset_skill_improver()
    improver = get_skill_improver()
    skill, registry = _skill_registry_with("旧版正文")
    service = SimpleNamespace(update_auto_skill=lambda **kwargs: True)
    monkeypatch.setattr(
        "neurova.evolution.skill_experience.get_skill_experience_store",
        lambda: SimpleNamespace(record_experience=lambda *a, **k: None),
    )

    ok = improver.apply_improvement(_proposal(), registry, skill_service=service)

    assert ok is True
    assert skill.config["context_template"] == "旧版正文"
    reset_skill_improver()


def test_service_decide_is_the_only_text_writer():
    """契约说明：正文写入点只有 service.decide → _apply_to_skill。"""
    import inspect

    from neurova.evolution.eval.service import SkillEvolutionService

    source = inspect.getsource(SkillEvolutionService._apply_to_skill)
    assert 'config["context_template"] = proposal["improved_text"]' in source
