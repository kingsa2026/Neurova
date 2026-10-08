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


# ── 归因与落盘：compute_skill_funnel_update / record_skill_funnel ──


from neurova.skills.skill_service import compute_skill_funnel_update  # noqa: E402


def testPresentedEntryCountsSeparatelyFromSelection():
    """呈现条目只加 presentations，不得冒领 selection。"""
    entries = [
        {"skill_id": "sk_a", "applied": False, "ok": False, "stage": "presented"},
        {"skill_id": "sk_a", "applied": True, "ok": True, "stage": "dispatch"},
    ]
    delta = compute_skill_funnel_update(entries, task_completed=True)["sk_a"]
    assert delta["presentations"] == 1 and delta["selections"] == 1
    assert delta["applications"] == 1 and delta["completions"] == 1


def testLegacyEntriesWithoutStageStillCountAsSelection():
    """历史条目无 stage 键：仍按派发计，presentations 为 0（零行为漂移）。"""
    delta = compute_skill_funnel_update(
        [{"skill_id": "sk_b", "applied": True, "ok": False}], task_completed=True)["sk_b"]
    assert delta["selections"] == 1 and delta["presentations"] == 0
    assert delta["fallbacks"] == 1  # 执行失败但本轮完成 → 兜底，不给 completion


def testTaskCompletionDoesNotAffectPresentations():
    delta = compute_skill_funnel_update(
        [{"skill_id": "sk_c", "applied": False, "ok": False, "stage": "presented"}],
        task_completed=False)["sk_c"]
    assert delta["presentations"] == 1 and delta["selections"] == 0


def testPresentationsPersistAndSurfaceOnReadFacets(tmp_path):
    """落盘与读数面都要携带 presentations——写穿 manifest 后必须在读口可见。

    只写不读正是本票要修的缺陷，读数面漏接等于再造一次断点。
    """
    import json

    from tests.unit.skills.creation_helpers import register_proven_skill
    from neurova.skills.skill_service import SkillService

    service = SkillService(agent_id="presq3", skills_dir=str(tmp_path / "skills"))
    register_proven_skill(service, "sk_a", name="sk_a", description="d")
    assert service.record_skill_funnel("sk_a", presentations=3, selections=1,
                                       applications=1, completions=1)
    manifest = json.loads((tmp_path / "skills" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sk_a"]["usage"]["presentations"] == 3
    assert service.get_skill_usage("sk_a")["presentations"] == 3


# ── 读侧：三态判据与 RSI 状态面 ──────────────────────────────


class _NullHost:
    """缺席占位宿主：类级声明 rsi_placeholder（与 integration_manager 的占位判据
    对齐）。不用 MagicMock 冒充业务对象——MagicMock().get("success") 恒真。"""
    rsi_placeholder = True


def testVerdictUnevidencedWhenNothingPresented():
    from neurova.evolution.skill_experience import presentationFunnelVerdict

    verdict = presentationFunnelVerdict([{"presentations": 0, "selections": 0}])
    assert verdict.state == "unevidenced"
    assert str(verdict.reason).strip(), "unevidenced 必须说得出为什么没量到"


def testVerdictFailsWhenFunnelBreaksAtFirstStage():
    """有呈现零派发 = 漏斗在第一节就断，这是"注入没人用"的可见形态。"""
    from neurova.evolution.skill_experience import presentationFunnelVerdict

    verdict = presentationFunnelVerdict([{"presentations": 4, "selections": 0}])
    assert verdict.state == "failed"
    assert verdict.evidence["presentations"] == 4


def testVerdictPassesWhenPresentationsConvert():
    from neurova.evolution.skill_experience import presentationFunnelVerdict

    verdict = presentationFunnelVerdict(
        [{"presentations": 4, "selections": 1}, {"presentations": 0, "selections": 0}]
    )
    assert verdict.state == "passed"
    assert verdict.evidence["selections"] == 1


def testVerdictIsNotFoldedWhenRowsMissing():
    """空读数不得折叠成 passed（无证据 ≠ 没问题）。"""
    from neurova.evolution.skill_experience import presentationFunnelVerdict

    assert presentationFunnelVerdict([]).state == "unevidenced"
    assert presentationFunnelVerdict(None).state == "unevidenced"


def testStatusSurfaceCarriesPresentationFunnel():
    """断点条款：写了没人读即红——状态面必须有这一格。"""
    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    orchestrator = RSIOrchestrator(
        sleep_system=_NullHost(), emotion_system=_NullHost(),
        experience_system=_NullHost(), tool_memory_system=_NullHost(),
    )
    status = orchestrator.get_status()
    assert "presentation_funnel" in status
    assert status["presentation_funnel"]["state"] in ("passed", "failed", "unevidenced")
