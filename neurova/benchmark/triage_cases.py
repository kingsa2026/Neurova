# -*- coding: utf-8 -*-
"""SB-5 分诊 EvalCase 案例集（suite triage-v1，subject triage-gate-verdicts）。

「先 case 后修」纪律（AGENTS.md §4）在分诊规则面上的立案（计划 §5.5 /
§8-SB-5）。每条 case 冻结一个合成会话事件窗口与期望裁决；check 忽略回答
措辞、现跑 `evaluateTriage(窗口)` 断言 action/reason，并与回答的动作比对——
规则阈值或级联语义漂移时案例先红，逼着先改 case 再改实现。

回答口径：`"allow"` / `"skip"`，或带原因的 `"skip/agent_loop_no_human"`
全形态（check 只取 "/" 前的动作段）。

级联冒烟案例（灰区 12 独走）走 `evaluateTriage` + `NeuJudge` 默认产物级联：
只断言级联给出确定裁决且特征非空，**不钉死模型档位**——权重重训不影响
本案例的有效性（防权重调整误杀案例）。

source 统一登记出处（review：small-brain-triage-gate-wiring-plan §SB-5）。
成本口径：判据全部确定性（纯规则 + 本地权重产物），零模型费用（cost_hint
显式标注 est_tokens=0）；评测手动跑，CI 只跑判据单测（D-H）。

import 即注册（沿 evolution_cases 惯例，消费方显式 import 触发）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from neurova.benchmark.suite_eval import EvalCase, listEvalCases, registerEvalCase
from neurova.collaboration.neu_judge import NeuJudge
from neurova.collaboration.triage_rules import evaluateTriage

#: 案例归属的评测 suite（与 reasoning/coding 等能力套件分列）。
CASE_SUITE_ID = "triage-v1"

#: 被守卫对象：分诊门的裁决行为（规则 + 级联语义）。
CASE_SUBJECT_ID = "triage-gate-verdicts"

#: case 出处：小脑分诊门接线计划 §8-SB-5（评审来源）。
CASE_SOURCE = {
    "kind": "review",
    "ref": "docs/04-plans/2026-11-22-small-brain-triage-gate-wiring-plan.md#SB-5",
}

#: 确定性判据零模型费用（D-H：评测手动跑 + 成本标注，CI 只跑判据单测）。
CASE_COST_HINT = {"model": "deterministic-rules", "est_tokens": 0}


@dataclass(frozen=True)
class TriageCaseSpec:
    """一条分诊案例的冻结输入与期望。

    window: 冻结会话事件窗口（{"role","content","timestamp"} 按时间升序）
    expect_action / expect_reason: 规则层冻结期望（现跑 evaluateTriage 必须复现）
    current_input: 本回合输入（参与 maxSimilarity 特征）
    cascade: True = 灰区级联案例（规则定区后追加 NeuJudge 档位，档位不钉死）
    """

    case_id: str
    window: Tuple[Dict[str, Any], ...]
    expect_action: str
    expect_reason: str
    current_input: str = ""
    cascade: bool = False


# ── 冻结窗口构造（时间戳固定，同输入同输出） ───────────────────────

_BASE_TIME = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)


def _event(role: str, content: str, index: int) -> Dict[str, Any]:
    return {
        "role": role,
        "content": content,
        "timestamp": (_BASE_TIME + timedelta(seconds=index * 5)).isoformat(),
    }


def _soloWindow(count: int, prefix: str = "solo loop message") -> Tuple[Dict[str, Any], ...]:
    """count 条互不相同的 assistant 消息（无人类）——独走窗口。"""
    return tuple(
        _event("assistant", f"{prefix} {i} with distinct content", i)
        for i in range(count)
    )


def _caseSpecs() -> List[TriageCaseSpec]:
    repeatText = "这条回复是逐字重复的样例长文本，用于触发复读环判定"
    verbatimWindow = tuple(
        _event("assistant", repeatText if i in (1, 3, 5) else f"独立回复内容 {i}", i)
        for i in range(6)
    )
    humanInWindow = (_event("user", "帮我看看这个方案", 0),) + tuple(
        _event("assistant", f"围绕方案的推进回复 {i}", i + 1) for i in range(8)
    )
    return [
        TriageCaseSpec(
            case_id="triage-empty-window-no-events",
            window=(),
            expect_action="allow",
            expect_reason="no_events",
        ),
        TriageCaseSpec(
            case_id="triage-human-last-allows",
            window=_soloWindow(4) + (_event("user", "我在，请继续", 4),),
            expect_action="allow",
            expect_reason="human_last",
        ),
        TriageCaseSpec(
            case_id="triage-human-in-window-allows",
            window=humanInWindow,
            expect_action="allow",
            expect_reason="human_in_window",
        ),
        TriageCaseSpec(
            case_id="triage-25-solo-agent-loop-skips",
            window=_soloWindow(25),
            expect_action="skip",
            expect_reason="agent_loop_no_human",
        ),
        TriageCaseSpec(
            case_id="triage-19-solo-boundary-default-allow",
            window=_soloWindow(19),
            expect_action="allow",
            expect_reason="default_allow",
        ),
        TriageCaseSpec(
            case_id="triage-verbatim-loop-skips",
            window=verbatimWindow,
            expect_action="skip",
            expect_reason="verbatim_loop",
        ),
        TriageCaseSpec(
            case_id="triage-gray-zone-cascade-smoke",
            window=_soloWindow(12),
            expect_action="allow",
            expect_reason="default_allow",
            cascade=True,
        ),
    ]


#: 冻结案例规格（单源；check 闭包与测试直读共用这一份）。
CASE_SPECS: Tuple[TriageCaseSpec, ...] = tuple(_caseSpecs())


# ── 裁决计算（check 与测试共用的单份实现） ─────────────────────────

def _actionOf(answer: str) -> str:
    """回答 → 动作段：取 "/" 前的部分（"skip/xxx" → "skip"）。"""
    text = str(answer or "").strip().lower()
    return text.split("/", 1)[0] if text else ""


def cascadeVerdict(spec: TriageCaseSpec) -> Tuple[str, Dict[str, float], bool]:
    """灰区级联现算（与闸同语义）：返回 (finalAction, features, modelAvailable)。

    规则高置信区直接定案；default_allow 灰区问 NeuJudge 默认产物——模型
    skip 才翻转为 skip，allow/abstain/产物不可用一律保守放行。
    """
    verdict = evaluateTriage(list(spec.window), spec.current_input)
    features = dict(verdict.features)
    if verdict.reason != "default_allow":
        return verdict.action, features, False
    try:
        model = NeuJudge.loadDefault()
    except Exception:  # noqa: BLE001 - 产物不可用：诚实降级为仅规则（与闸同构）
        return verdict.action, features, False
    decision = model.decide(model.score(features))
    if decision == "skip":
        return "skip", features, True
    return "allow", features, True


def _ruleCheck(spec: TriageCaseSpec):
    def _check(answer: str) -> Tuple[bool, float, dict]:
        verdict = evaluateTriage(list(spec.window), spec.current_input)
        verdictMatches = (
            verdict.action == spec.expect_action and verdict.reason == spec.expect_reason
        )
        answerMatches = _actionOf(answer) == verdict.action
        passed = verdictMatches and answerMatches
        details = {
            "expected_action": spec.expect_action,
            "expected_reason": spec.expect_reason,
            "verdict_action": verdict.action,
            "verdict_reason": verdict.reason,
            "answered": str(answer or ""),
        }
        return passed, (1.0 if passed else 0.0), details

    return _check


def _cascadeCheck(spec: TriageCaseSpec):
    def _check(answer: str) -> Tuple[bool, float, dict]:
        verdict = evaluateTriage(list(spec.window), spec.current_input)
        ruleMatches = (
            verdict.action == spec.expect_action and verdict.reason == spec.expect_reason
        )
        finalAction, features, modelAvailable = cascadeVerdict(spec)
        answered = _actionOf(answer)
        passed = (
            ruleMatches
            and finalAction in ("allow", "skip")
            and bool(features)
            and answered == finalAction
        )
        details = {
            "expected_action": spec.expect_action,
            "expected_reason": spec.expect_reason,
            "verdict_action": verdict.action,
            "verdict_reason": verdict.reason,
            "cascade_action": finalAction,
            "model_available": modelAvailable,
            "features_non_empty": bool(features),
            "answered": str(answer or ""),
        }
        return passed, (1.0 if passed else 0.0), details

    return _check


# ── 注册 ───────────────────────────────────────────────────────────

def _promptFor(spec: TriageCaseSpec) -> str:
    lines = [f"事件 {i}（{e['role']}）：{e['content']}" for i, e in enumerate(spec.window)]
    body = "\n".join(lines) if lines else "（空窗口，无任何事件）"
    return (
        f"以下是某会话的事件窗口（按时间升序）：\n{body}\n"
        f"本回合输入：{spec.current_input or '（空）'}\n"
        "分诊门对该回合应放行还是跳过？只回答 allow 或 skip。"
    )


def buildTriageCases() -> List[EvalCase]:
    """按冻结规格构建案例集（每次新实例，注册表去重交给 registerTriageCases）。"""
    cases: List[EvalCase] = []
    for spec in CASE_SPECS:
        cases.append(EvalCase(
            case_id=spec.case_id,
            suite_id=CASE_SUITE_ID,
            prompt=_promptFor(spec),
            check=_cascadeCheck(spec) if spec.cascade else _ruleCheck(spec),
            subject_id=CASE_SUBJECT_ID,
            source=dict(CASE_SOURCE),
            cost_hint=dict(CASE_COST_HINT),
        ))
    return cases


def registerTriageCases() -> None:
    """注册分诊案例集（幂等：已登记的 case_id 跳过，可安全重复调用）。"""
    existing = {case.case_id for case in listEvalCases()}
    for case in buildTriageCases():
        if case.case_id in existing:
            continue
        registerEvalCase(case)


# import 即立案（消费方显式 import 本模块即触发）。
registerTriageCases()
