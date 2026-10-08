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


# ── 写入方：技能目录渲染与 orchestrator 挂接 ──────────────────


import types

from neurova.skills.skill_injection import render_skill_catalog


def _registry(names):
    return types.SimpleNamespace(
        skills={
            n: types.SimpleNamespace(enabled=True, config={}, description="d")
            for n in names
        }
    )


def _catalogStub(names, budget=8000):
    """把真方法绑到 stub 上调用（仓内既有形态，
    先例 tests/unit/skills/test_recall_injection_wave_b.py:170-179）。"""
    from neurova.context.orchestrator import ContextOrchestrator

    class _Cfg:
        skill_catalog_enabled = True
        skill_catalog_budget_chars = budget

    stub = types.SimpleNamespace(config=_Cfg(), skill_registry=_registry(names))
    stub._resolve_recall_flag = types.MethodType(
        ContextOrchestrator._resolve_recall_flag, stub
    )
    return types.MethodType(ContextOrchestrator._skill_catalog_section, stub)()


def testCatalogSectionRecordsPresentedSkills():
    clear_turn_state()
    text = _catalogStub({"sk_a", "sk_b"})
    assert "可用技能目录" in text
    assert sorted(e["skill_id"] for e in _presented()) == ["sk_a", "sk_b"]


def testCatalogSectionColdArmRecordsNothing():
    """cold 臂（turn skills_off）目录段整体为空，不得产生呈现——P2-4 A/B 语义前提。"""
    from neurova.core.turn_context import reset_turn_skills_off, set_turn_skills_off

    clear_turn_state()
    token = set_turn_skills_off(True)
    try:
        assert _catalogStub({"sk_a"}) == ""
        assert _presented() == []
    finally:
        reset_turn_skills_off(token)


def testCatalogSectionPresentedOncePerTurnAcrossBothRenderPaths():
    """build_context 与 build_system_prompt 共用同一单源 helper：一轮两次调用只记一次。"""
    clear_turn_state()
    _catalogStub({"sk_a"})
    _catalogStub({"sk_a"})
    assert len(_presented()) == 1


def testRendererReportsOnlyKeptLines():
    """被 max_lines 裁掉的技能没进 prompt，不得计呈现。"""
    clear_turn_state()
    seen = []
    render_skill_catalog(_registry({f"sk_{i}" for i in range(10)}), max_lines=3,
                         on_present=seen.append)
    assert len(seen) == 3


def testRendererWithoutCallbackKeepsTextIdentical():
    """on_present 是旁路观察者：不传时目录文本与既有契约逐字一致。"""
    clear_turn_state()
    text = render_skill_catalog(_registry({"sk_a"}), max_chars=8000)
    assert text == "- sk_a — d"
    assert _presented() == []


def testCatalogSectionViewBranchRoutesProvenance():
    """视图分支（三层库）是同一处改动的另一个命中点：呈现照记，且账目按副本所在库路由。"""
    from neurova.core.turn_context import reset_turn_skill_view, set_turn_skill_view
    from neurova.skills.skill_visibility import SkillView

    clear_turn_state()
    view = SkillView(agent_id="own")
    view.skills = {
        "sk_user": types.SimpleNamespace(
            enabled=True, config={}, description="d",
            pool="user", owner_key="u_7", entry={},
        )
    }
    token = set_turn_skill_view(view)
    try:
        assert "可用技能目录" in _catalogStub(set())
        rows = _presented()
        assert [(r["skill_id"], r["pool"], r["owner_key"]) for r in rows] == [
            ("sk_user", "user", "u_7")
        ]
    finally:
        reset_turn_skill_view(token)
