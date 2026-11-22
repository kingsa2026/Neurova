# -*- coding: utf-8 -*-
"""SB-5 分诊 EvalCase 案例集判据（suite triage-v1，subject triage-gate-verdicts）。

出处：docs/04-plans/2026-11-22-small-brain-triage-gate-wiring-plan.md
§5.5 评测与棘轮 / §8-SB-5。

钉住三件事：
1. 立案面：triage-v1 suite 至少 7 条 case 已注册，subject/source/成本口径齐全；
2. 判据咬合：skip 期望案例对"旧空壳行为（恒 allow）"必须红、对"真裁决"
   必须绿（assertCaseRedGreen 先红后绿自检）；
3. 窗口冻结：案例窗口现跑 evaluateTriage 仍产出期望 action/reason——
   规则阈值漂移时案例先红，逼着先改 case 再改实现（先 case 后修）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from neurova.benchmark.suite_eval import (  # noqa: E402
    assertCaseRedGreen,
    clearEvalCases,
    listEvalCases,
    validateCaseFirst,
)
from neurova.benchmark.triage_cases import (  # noqa: E402
    CASE_SOURCE,
    CASE_SUBJECT_ID,
    CASE_SUITE_ID,
    CASE_SPECS,
    cascadeVerdict,
    registerTriageCases,
)
from neurova.collaboration.triage_rules import evaluateTriage  # noqa: E402


@pytest.fixture(autouse=True)
def _triageCaseRegistry():
    """eval case 注册表是模块级全局：每例前清空并重装，保证互不串扰。"""
    clearEvalCases()
    registerTriageCases()
    yield
    clearEvalCases()


def _caseById(caseId: str):
    for case in listEvalCases(CASE_SUITE_ID):
        if case.case_id == caseId:
            return case
    raise AssertionError(f"案例未注册: {caseId}")


def _specById(caseId: str):
    for spec in CASE_SPECS:
        if spec.case_id == caseId:
            return spec
    raise AssertionError(f"案例规格缺失: {caseId}")


# ── 立案面 ─────────────────────────────────────────────────────────

def testTriageCasesRegisteredWithSourceAndCost():
    cases = listEvalCases(CASE_SUITE_ID)
    assert len(cases) >= 7, f"分诊案例集至少 7 条，实得 {len(cases)}"
    for case in cases:
        assert case.subject_id == CASE_SUBJECT_ID
        assert case.source == CASE_SOURCE
        assert case.source["kind"] in ("issue", "incident", "review")
        assert case.source["ref"].strip()
        assert case.prompt.strip()
        assert callable(case.check)
        assert case.cost_hint is not None, "案例须带成本口径标注"


def testCaseFirstCoversTriageSubject():
    report = validateCaseFirst([CASE_SUBJECT_ID])
    assert report["missing"] == []
    assert report["covered"] == [CASE_SUBJECT_ID]


# ── 窗口冻结：现跑规则仍产出冻结期望 ───────────────────────────────

def testFrozenWindowsStillProduceExpectedVerdicts():
    for spec in CASE_SPECS:
        verdict = evaluateTriage(list(spec.window), spec.current_input)
        assert (verdict.action, verdict.reason) == (spec.expect_action, spec.expect_reason), (
            f"{spec.case_id}: 规则现裁决 {verdict.action}/{verdict.reason} ≠ "
            f"冻结期望 {spec.expect_action}/{spec.expect_reason}（规则漂移请先改 case）"
        )


def testEveryDeterministicCaseCheckPassesWithTrueVerdict():
    for spec in CASE_SPECS:
        if spec.cascade:
            continue
        case = _caseById(spec.case_id)
        passed, score, details = case.check(f"{spec.expect_action}/{spec.expect_reason}")
        assert passed, f"{spec.case_id} 真裁决未通过: {details}"
        assert score == 1.0


def testEverySkipCaseFailsWithLegacyAlwaysAllow():
    """旧空壳行为（恒 allow）在全部 skip 期望案例上必须红。"""
    for spec in CASE_SPECS:
        if spec.expect_action != "skip":
            continue
        case = _caseById(spec.case_id)
        passed, _score, details = case.check("allow")
        assert not passed, f"{spec.case_id} 对旧空壳行为未红: {details}"


def testSkipCaseRedGreenSelfCheck():
    """先红后绿自检：旧空壳（恒 allow）必 FAIL，真裁决必 PASS。"""
    case = _caseById("triage-25-solo-agent-loop-skips")
    assertCaseRedGreen(
        case,
        oldAnswerFn=lambda prompt: "allow",
        newAnswerFn=lambda prompt: "skip/agent_loop_no_human",
    )


# ── 级联冒烟（模型档位不钉死，防权重调整误杀案例） ─────────────────

def testCascadeCaseSmoke():
    spec = _specById("triage-gray-zone-cascade-smoke")
    case = _caseById(spec.case_id)

    finalAction, features, _modelAvailable = cascadeVerdict(spec)

    assert finalAction in ("allow", "skip"), f"级联必须给出确定裁决，实得 {finalAction!r}"
    assert features, "级联案例特征向量不得为空"

    passed, score, details = case.check(finalAction)
    assert passed, f"级联冒烟未通过: {details}"
    assert score == 1.0
