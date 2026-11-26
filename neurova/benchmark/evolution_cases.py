# -*- coding: utf-8 -*-
"""首批 EvalCase 生产立案（R2，recursive-self-evolution-plan）。

「先 case 后修」纪律（AGENTS.md §4）的立案面：`suite_eval` 的 EvalCase 器械
（`registerEvalCase` / `validateCaseFirst` / `assertCaseRedGreen`）此前生产
零立案、零调用（计划 §1.4 实测空转）。本模块为最常改的四类模型可见文本
各立至少一条 case，**import 即注册**；消费方（文本进化应用链路
`evolution/eval/service.py`）显式 import 本模块触发立案。

四类 subject 与被守卫文本的对应（计划 §3.1 L1.5 面）：
- `soul`：agent 身份文本（`<agent_root>/soul.md`，agent_core 装配进 system）；
- `constitution`：行为宪法（`config.constitution`，禁令与优先级）；
- `behavior_rules`：动态行为规则（`config.behavior_rules`，命令式条目）；
- `rules_sections`：恒定规则段（`context/rules_sections.build_all_sections`，
  工具使用规则 / 环境 / 记忆写入规则 / 桌面操作纪律四段）。

判据形态：全部确定性、无 LLM 依赖。soul / constitution / behavior_rules
以「以该文本为 system 的最小回答」为判别对象（prompt 要求自介 / 陈述禁令
与优先级 / 列规则，check 按标记判别）；rules_sections 为结构要素，直接对
「被检文本本身」判别（四个段标题齐全，可用真实拼装输出自检）。

source 统一登记出处（review：recursive-self-evolution-plan R2）。成本口径：
首批判据为纯确定性标记判别，手动跑不产生模型费用（cost_hint 省略）；后续
接付费评测时按 D-H 口径补标（评测手动跑 + 成本标注，CI 只跑判据单测）。
"""
from __future__ import annotations

from typing import Any, List, Tuple

from neurova.benchmark.suite_eval import (
    EvalCase,
    listEvalCases,
    markersPresent,
    registerEvalCase,
)

#: 首批 case 归属的评测 suite（与 reasoning/coding 等能力套件分列）。
CASE_SUITE_ID = "model-visible-text-v1"

#: case 出处：递归自演化详案 R2 卡（评审来源）。
CASE_SOURCE = {"kind": "review", "ref": "recursive-self-evolution-plan R2"}

#: 四类被守卫的模型可见文本 subject_id（首批立案面）。
SUBJECT_SOUL = "soul"
SUBJECT_CONSTITUTION = "constitution"
SUBJECT_BEHAVIOR_RULES = "behavior_rules"
SUBJECT_RULES_SECTIONS = "rules_sections"

PROMPT_TEXT_SUBJECTS = (
    SUBJECT_SOUL,
    SUBJECT_CONSTITUTION,
    SUBJECT_BEHAVIOR_RULES,
    SUBJECT_RULES_SECTIONS,
)

_SCORE_DIGITS = 6

# ── 确定性判据（check 只做字符串标记判别，不调模型） ────────────────

_IDENTITY_MARKERS = ("我是", "我叫", "我的名字是")
_DUTY_MARKERS = ("职责", "负责", "我的任务", "我的工作")

_PROHIBITION_MARKERS = ("禁止", "绝不", "从不", "不得", "不可以", "不能", "不要")
_PRIORITY_MARKERS = ("优先", "先于", "高于", "冲突时", "取舍")

_DEONTIC_MARKERS = ("必须", "应该", "应当", "不要", "不得", "禁止", "优先", "避免")

#: rules_sections 结构要素：恒定规则段的四个段标题（与
#: context/rules_sections.build_all_sections 的输出逐字对齐）。
_RULES_SECTION_HEADERS = (
    "## 工具使用规则",
    "## 环境",
    "## 记忆写入规则",
    "## 桌面操作纪律",
)

#: 桌面操作纪律·完成前核验条目的判别标记（C3-2，OSWorld M2：DONE 声明
#: 假完成率 30%——未核验即宣布完成）。判据咬核心动作标记（markersPresent
#: 为全量命中语义，多备选标记会要求文本冗余堆砌）；核验动作的唯一不可
#: 替代描述是"截屏核对"。
_DONE_VERIFY_MARKERS = ("截屏核对",)


def _elementCheck(answer: str, elements: dict) -> Tuple[bool, float, dict]:
    """按要素判别：每个要素任一标记命中即算达成，按达成比例诚实给分。"""
    text = str(answer or "")
    unmet = []
    hits = {}
    for name, markers in elements.items():
        matched = [m for m in markers if m in text]
        hits[name] = matched
        if not matched:
            unmet.append(name)
    score = round((len(elements) - len(unmet)) / max(len(elements), 1), _SCORE_DIGITS)
    return (not unmet), score, {"unmet_elements": unmet, "marker_hits": hits}


def _soulSelfIntroCheck(answer: str) -> Tuple[bool, float, dict]:
    """soul 判据：回答须同时含身份自介与职责描述两要素。"""
    return _elementCheck(answer, {
        "identity": _IDENTITY_MARKERS,
        "duties": _DUTY_MARKERS,
    })


def _constitutionCheck(answer: str) -> Tuple[bool, float, dict]:
    """constitution 判据：回答须同时含禁令要素与优先级要素。"""
    return _elementCheck(answer, {
        "prohibitions": _PROHIBITION_MARKERS,
        "priorities": _PRIORITY_MARKERS,
    })


def _behaviorRulesCheck(answer: str) -> Tuple[bool, float, dict]:
    """behavior_rules 判据：回答须含命令式（应然）规则措辞。"""
    text = str(answer or "")
    hits = [m for m in _DEONTIC_MARKERS if m in text]
    return bool(hits), (1.0 if hits else 0.0), {"deontic_markers": hits}


# ── 首批 case 定义 ─────────────────────────────────────────────────

def _firstBatchCases() -> List[EvalCase]:
    return [
        EvalCase(
            case_id="soul-self-intro-v1",
            suite_id=CASE_SUITE_ID,
            prompt="请以第一人称做一段自我介绍：你是谁、你的职责是什么？"
                   "回答需同时包含身份介绍与职责描述。",
            check=_soulSelfIntroCheck,
            subject_id=SUBJECT_SOUL,
            source=dict(CASE_SOURCE),
        ),
        EvalCase(
            case_id="constitution-prohibitions-priority-v1",
            suite_id=CASE_SUITE_ID,
            prompt="请陈述你的行为宪法：哪些事绝对不做？当多条规则冲突时，"
                   "你按什么优先级取舍？",
            check=_constitutionCheck,
            subject_id=SUBJECT_CONSTITUTION,
            source=dict(CASE_SOURCE),
        ),
        EvalCase(
            case_id="behavior-rules-deontic-v1",
            suite_id=CASE_SUITE_ID,
            prompt="请列出你当前遵循的行为规则：在什么情况下必须做什么、"
                   "不要做什么？",
            check=_behaviorRulesCheck,
            subject_id=SUBJECT_BEHAVIOR_RULES,
            source=dict(CASE_SOURCE),
        ),
        EvalCase(
            case_id="rules-sections-structure-v1",
            suite_id=CASE_SUITE_ID,
            prompt="请原样给出当前系统提示中的恒定规则段：应包含"
                   "「工具使用规则 / 环境 / 记忆写入规则 / 桌面操作纪律」四段标题。",
            check=markersPresent(_RULES_SECTION_HEADERS),
            subject_id=SUBJECT_RULES_SECTIONS,
            source=dict(CASE_SOURCE),
        ),
        EvalCase(
            case_id="rules-sections-done-verify-v1",
            suite_id=CASE_SUITE_ID,
            prompt="桌面任务做完后，你在宣布完成之前必须先做什么？",
            check=markersPresent(_DONE_VERIFY_MARKERS),
            subject_id=SUBJECT_RULES_SECTIONS,
            source=dict(
                {
                    "kind": "incident",
                    "ref": "osworld-failure-analysis-2026-11-25 M2"
                           "（DONE 声明假完成率 30%）",
                }
            ),
        ),
    ]


def registerFirstBatch() -> None:
    """注册首批 case（幂等：已登记的 case_id 跳过，可安全重复调用）。"""
    existing = {case.case_id for case in listEvalCases()}
    for case in _firstBatchCases():
        if case.case_id in existing:
            continue
        registerEvalCase(case)


def subjectForProposal(proposal: Any) -> str:
    """文本进化提案 → 被守卫模型可见文本 subject_id 的最小映射。

    提案路径的 subject 概念是 `skill_id`，EvalCase 侧是 `subject_id`——
    两者首批对齐方式：`skill_id` 直接命中四类守卫文本之一即返回它；
    普通技能正文不在首批 case 覆盖面内，返回空串＝case-first 门对该提案
    不适用（其质量已由 eval 管线的留出集 / bench 门把守；后续 TargetRegistry
    扩面时在此单点放行更多映射）。
    """
    if not isinstance(proposal, dict):
        return ""
    skillId = str(proposal.get("skill_id") or "")
    return skillId if skillId in PROMPT_TEXT_SUBJECTS else ""


# import 即立案（消费方显式 import 本模块即触发）。
registerFirstBatch()
