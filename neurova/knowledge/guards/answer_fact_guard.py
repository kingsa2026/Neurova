# -*- coding: utf-8 -*-
"""生成后事实回查守卫（specs/2026-10-30 W5）。

本回合有事实血缘命中时，对草稿答案做**句级确定性回查**：答案里的数字/日期
性声明能否在命中证据（事实 object 值 + 命中条目正文）里核到；核不到的以
诚实形态暴露，不静默、不自动改写。

纪律四条：

- **零额外 LLM**：断言抽取只用数字/日期正则，不引入模型调用；
- **判定从保守**：contradicted 仅当同主体确有**另一个**数值事实、且答案里的
  那个值在任何命中证据里都查不到；其余归 unverified（宁可少报，不可误伤）；
- **只标记不改写**：报告只进 metadata（shadow）/ 末尾追加一行注记（on），
  原句一字不动；
- **失败让路**：事实库或血缘任何异常 → 返回 None，消息照发（debug 日志）。

开关 `NEUROVA_KB_ANSWER_FACT_GUARD=off|shadow|on`，默认 off；
无血缘回合整个守卫不启动——不产生读数，也不碰消息。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

ANSWER_FACT_GUARD_ENV = "NEUROVA_KB_ANSWER_FACT_GUARD"
_MODES = ("off", "shadow", "on")

_SENTENCE_SPLIT = re.compile(r"[。！？!?\n]+")
# 数值/百分比/量词与日期；不做单位归一（归一就是"猜等值"，本守卫不做）
_CLAIM_PATTERN = re.compile(
    r"\d{4}\s*[-/年]\s*\d{1,2}(?:\s*[-/月]\s*\d{1,2})?\s*[日号]?"
    r"|\d+(?:[.,]\d+)*\s*(?:%|％|个百分点|万|亿|千|百|元|块|人|次|天|个月|年)?"
)
_DIGIT_GROUP = re.compile(r"[\d%％.,万千亿百元块人次天个年月日号]+")


def guardMode() -> str:
    raw = (os.environ.get(ANSWER_FACT_GUARD_ENV) or "off").strip().lower()
    return raw if raw in _MODES else "off"


@dataclass
class FactClaim:
    sentence: str
    claim: str
    evidenceStatus: str  # supported | contradicted | unverified
    subjectKey: str = ""


@dataclass
class GuardReport:
    checked: int = 0
    supported: int = 0
    unverified: int = 0
    contradicted: List[Dict[str, Any]] = field(default_factory=list)
    mode: str = "shadow"

    def toMetadata(self) -> Dict[str, Any]:
        return {
            "checked": self.checked,
            "supported": self.supported,
            "unverified": self.unverified,
            "contradicted": [dict(item) for item in self.contradicted],
            "mode": self.mode,
        }


def _normalizeNumber(text: str) -> str:
    return str(text or "").replace(",", "").replace("，", "").strip()


def _labelsOf(store: Any, subjectKey: str) -> List[str]:
    try:
        subject = store.subjectFor(subjectKey) or {}
    except Exception as exc:  # noqa: BLE001 - 主体读失败只少一种叫法
        logger.debug("事实回查主体读失败: %s", exc)
        return []
    labels = [str(subject.get("canonical_label") or "")]
    labels += [str(alias) for alias in (subject.get("aliases") or [])]
    return [label for label in labels if label.strip()]


def _evidenceText(hits: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for hit in hits or []:
        if not isinstance(hit, dict):
            parts.append(str(hit))
            continue
        for key in ("content", "title"):
            text = str(hit.get(key) or "")
            if text:
                parts.append(text)
    return "\n".join(parts)


def _numericFactValues(facts: List[Dict[str, Any]]) -> List[str]:
    values: List[str] = []
    for fact in facts or []:
        for value in (fact.get("object_term"), (fact.get("qualifier") or {}).get("value")):
            text = _normalizeNumber(str(value or ""))
            if text and _DIGIT_GROUP.search(text) and text not in values:
                values.append(text)
    return values


def runAnswerFactGuard(
    draft: str,
    hits: List[Dict[str, Any]],
    store: Any,
    agentId: Optional[str],
    tenantId: str = "default",
) -> Optional[GuardReport]:
    """对草稿做句级回查；开关 off / 无血缘 / 任何异常一律 None。"""
    mode = guardMode()
    if mode == "off":
        return None
    lineageIds = [
        str(hit.get("lineage_id")) for hit in hits or []
        if isinstance(hit, dict) and hit.get("lineage_id")
    ]
    if not lineageIds:
        return None  # 无血缘回合：守卫不启动，不产生读数也不碰消息
    text = str(draft or "")
    if not text.strip():
        return None
    try:
        facts = store.factsByIds(list(dict.fromkeys(lineageIds))) or []
    except Exception as exc:  # noqa: BLE001 - 事实库故障守卫静默让路，消息照发
        logger.debug("事实回查跳过（事实库不可用）: %s", exc)
        return None
    if not facts:
        return None

    factsBySubject: Dict[str, List[Dict[str, Any]]] = {}
    labelsBySubject: Dict[str, List[str]] = {}
    for fact in facts:
        subjectKey = str(fact.get("subject_key") or "")
        if not subjectKey:
            continue
        factsBySubject.setdefault(subjectKey, []).append(fact)
        if subjectKey not in labelsBySubject:
            labelsBySubject[subjectKey] = _labelsOf(store, subjectKey)

    evidence = _evidenceText(hits)
    evidenceNormalized = _normalizeNumber(evidence)
    report = GuardReport(mode=mode)

    for sentence in _SENTENCE_SPLIT.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        matchedSubjects = [
            subjectKey for subjectKey, labels in labelsBySubject.items()
            if any(label and label in sentence for label in labels)
        ]
        if not matchedSubjects:
            continue
        claims = [claim.strip() for claim in _CLAIM_PATTERN.findall(sentence) if claim.strip()]
        if not claims:
            continue  # 无数字/日期的句子不进 checked
        report.checked += 1
        subjectKey = matchedSubjects[0]
        factValues = _numericFactValues(factsBySubject.get(subjectKey) or [])
        for claim in claims:
            normalized = _normalizeNumber(claim)
            if normalized and (normalized in evidenceNormalized or normalized in factValues):
                report.supported += 1
                continue
            otherValues = [value for value in factValues if value != normalized]
            if otherValues:
                report.contradicted.append({
                    "sentence": sentence,
                    "claim": claim,
                    "evidenceStatus": "contradicted",
                    "subject_key": subjectKey,
                })
            else:
                report.unverified += 1
    return report


def renderGuardNote(report: GuardReport) -> str:
    """on 档消息末尾的可见核验注记（只列不符声明，不重写答案）。"""
    claims = "、".join(
        str(item.get("claim") or "") for item in report.contradicted if item.get("claim")
    )
    return f"（核验注记：以下数值未在知识库证据中核到：{claims}）"
