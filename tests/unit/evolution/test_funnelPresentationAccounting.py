"""技能漏斗的「呈现」级条目判据（对照报告 §8 前置 3 落地票面）。

钉住三件事：
- 呈现与派发同在一份轮次账本上（不新造第二本账）；
- 一轮一技能只记一次呈现（目录段由 build_context 与 build_system_prompt 两条
  路径共用，逐次累加会把一轮读成两轮）；
- 既有派发调用不带 stage，必须仍按 dispatch 处理（零行为漂移）。
"""

from neurova.core.turn_context import (
    clear_turn_state,
    get_turn_skill_funnel,
    record_turn_skill_funnel,
    recordTurnSkillPresentation,
)


def _presented():
    return [e for e in get_turn_skill_funnel() if e["stage"] == "presented"]


def testPresentedEntryLandsInSameLedger():
    clear_turn_state()
    recordTurnSkillPresentation("sk_a")
    entries = _presented()
    assert [(e["skill_id"], e["applied"], e["ok"]) for e in entries] == [("sk_a", False, False)]


def testPresentedDedupedPerTurnPerSkill():
    clear_turn_state()
    recordTurnSkillPresentation("sk_a")
    recordTurnSkillPresentation("sk_a")
    assert len(_presented()) == 1


def testDispatchEntriesDefaultStageKeepsOldSemantics():
    clear_turn_state()
    record_turn_skill_funnel("sk_b", applied=True, ok=True)
    entry = get_turn_skill_funnel()[0]
    assert entry["stage"] == "dispatch"
    assert entry["applied"] is True and entry["ok"] is True


def testNewTurnRebindDoesNotCarryOverPresentation():
    """轮首换绑：上一轮的呈现不得续进本轮（清零会把旧账续写进新轮）。"""
    clear_turn_state()
    recordTurnSkillPresentation("sk_a")
    clear_turn_state()
    recordTurnSkillPresentation("sk_a")
    assert len(_presented()) == 1
