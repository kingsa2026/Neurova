# -*- coding: utf-8 -*-
"""评测棘轮自动化（P3-3，recursive-self-evolution-plan）。

「失败案例自动沉淀 EvalCase，判据逻辑仍人工」：

- 自动通道只做**登记**——把一次失败（suite_eval 失败例 / RSI 例级回归 C1 /
  人工标记）转成 `suite_eval.EvalCase` 注册进 case 注册表，让该 subject 的
  case 覆盖只进不退（棘轮）；
- **判据逻辑仍人工**：自动立案的 check 只接受**判据白名单模板**的参数化
  实例（suite_eval 的 `exactAnswer` / `markersPresent`，经
  `CRITERION_TEMPLATE_ATTR` 标记核验），任意手写代码判据一律拒收——防自动
  通道夹带任意代码（裁判件保护）。白名单是 forbidden 语义的模块常量：
  **改白名单＝改规则**，只走人工 PR + 守卫红绿，自动通道不可达；
- **subject_id 对齐 R2 四 subject 体系**（`evolution_cases.PROMPT_TEXT_SUBJECTS`
  单源）：自动通道只能在已有人工立案面的 subject 上加厚覆盖，不能自创
  守卫面；新 subject / 新判据模板都走人工立案；
- **source 强制** `{kind: incident|issue|review, ref 非空}`——失败案例必须
  可追溯，匿名失败不入册。

接线说明：本卡只交付 sink + 来源钩子 + 测试，**不主动挂进**
`rsi/orchestrator.run_iteration`（在 P1-3 已交付的世代管线之外，属可选增强）。
建议接线点：`GenerationOrchestrator.observeOpenCanaries` /
`RSIOrchestrator.run_iteration` 取到 `case_metrics`（C1 读数）之后、
回滚判定之前——把 `case_regressions` 逐例喂给 `fromRegression`，让实测
退化例即时沉淀为该 subject 的守卫 case；金丝雀/回滚链路不受影响（本 sink
fail-soft，三态返回、不抛异常）。
"""
from __future__ import annotations

import hashlib
import threading
from typing import Any, Dict, Optional

from neurova.benchmark.evolution_cases import CASE_SUITE_ID, PROMPT_TEXT_SUBJECTS
from neurova.benchmark.suite_eval import (
    CASE_SOURCE_KINDS,
    CRITERION_TEMPLATE_ATTR,
    EvalCase,
    registerEvalCase,
)
from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 判据白名单（forbidden 语义）：自动立案只接受这些模板的参数化实例。
#: 改这个集合＝改规则，只走人工 PR + 守卫红绿；自动演化通道不可达。
CRITERION_TEMPLATE_WHITELIST = frozenset({"exactAnswer", "markersPresent"})

#: 去重账本（模块级，与 suite_eval case 注册表同寿命）：dedupKey → case_id。
#: dedupKey 语义＝「subject + 失败签名」（如 subject+失败签名 hash）：
#: 同签名失败只立一件，不重复立案。
_DEDUP_LOCK = threading.RLock()
_DEDUP_STORE: Dict[str, str] = {}

_SINK_LOCK = threading.RLock()
_SINK: Optional["RatchetSink"] = None

REGISTERED = "registered"
DUPLICATE = "duplicate"
REJECTED = "rejected"

_CASE_ID_PREFIX = "ratchet-"
_CASE_ID_HASH_LEN = 24


def caseIdForDedup(dedupKey: str) -> str:
    """dedupKey → 确定性 case_id：同签名永远映射同一件，天然幂等。"""
    digest = hashlib.sha256(dedupKey.encode("utf-8")).hexdigest()
    return f"{_CASE_ID_PREFIX}{digest[:_CASE_ID_HASH_LEN]}"


def _validSource(sourceRef: Any) -> bool:
    """source 强制 {kind ∈ incident|issue|review, ref 非空}（与 suite_eval 同规）。"""
    if not isinstance(sourceRef, dict):
        return False
    if sourceRef.get("kind") not in CASE_SOURCE_KINDS:
        return False
    ref = sourceRef.get("ref")
    return isinstance(ref, str) and bool(ref.strip())


class RatchetSink:
    """失败案例 → EvalCase 的自动沉淀池（评测棘轮入口）。

    实例无私有状态：去重账本与 case 注册表都是模块级单面（教义第 6 条），
    多个实例共享同一份棘轮。生产入口走 `getRatchetSink()` 单例。
    """

    def registerFailureCase(
        self,
        *,
        subjectId: str,
        prompt: str,
        check: Any,
        sourceRef: Any,
        dedupKey: str,
    ) -> str:
        """把一次失败自动转成 EvalCase 注册，返回三态：

        - ``registered``：立案成功；
        - ``duplicate``：同 dedupKey（subject+失败签名）已立案，不重复；
        - ``rejected``：判据非白名单模板 / subject 越出 R2 四 subject 体系 /
          source 缺失或形态非法 / prompt 或 dedupKey 空——自动通道
          fail-soft，不抛异常打断调用方管线。
        """
        template = getattr(check, CRITERION_TEMPLATE_ATTR, None)
        if template not in CRITERION_TEMPLATE_WHITELIST:
            logger.warning(
                "[ratchet] 拒收非白名单判据（template=%r，subject=%r）——"
                "判据逻辑仍人工，自动通道只收白名单模板的参数化实例",
                template, subjectId,
            )
            return REJECTED
        if subjectId not in PROMPT_TEXT_SUBJECTS:
            logger.warning(
                "[ratchet] 拒收越界 subject=%r（只收 R2 四 subject 体系 %s）",
                subjectId, PROMPT_TEXT_SUBJECTS,
            )
            return REJECTED
        if not isinstance(prompt, str) or not prompt.strip():
            logger.warning("[ratchet] 拒收空 prompt（subject=%r）", subjectId)
            return REJECTED
        if not _validSource(sourceRef):
            logger.warning(
                "[ratchet] 拒收非法 source=%r（须 {'kind': incident|issue|review, 'ref': 非空}）",
                sourceRef,
            )
            return REJECTED
        if not isinstance(dedupKey, str) or not dedupKey.strip():
            logger.warning("[ratchet] 拒收空 dedupKey（subject=%r）", subjectId)
            return REJECTED

        caseId = caseIdForDedup(dedupKey)
        with _DEDUP_LOCK:
            if dedupKey in _DEDUP_STORE:
                return DUPLICATE
        case = EvalCase(
            case_id=caseId,
            suite_id=CASE_SUITE_ID,
            prompt=prompt,
            check=check,
            subject_id=subjectId,
            source=dict(sourceRef),
        )
        try:
            registerEvalCase(case)
        except ValueError as exc:
            # 去重账本被清而注册表仍在（测试隔离的常见组合）→ case_id 撞册
            # ＝重复立案；其余校验失败（理论不可达）防御性归入拒收。
            duplicate = "重复注册" in str(exc)
            if duplicate:
                with _DEDUP_LOCK:
                    _DEDUP_STORE[dedupKey] = caseId
            logger.warning("[ratchet] 立案未成 dedupKey=%s: %s", dedupKey, exc)
            return DUPLICATE if duplicate else REJECTED
        with _DEDUP_LOCK:
            _DEDUP_STORE[dedupKey] = caseId
        logger.info(
            "[ratchet] 失败案例已立案 case=%s subject=%s dedupKey=%s",
            caseId, subjectId, dedupKey,
        )
        return REGISTERED

    def fromRegression(
        self,
        caseMetrics: Any,
        *,
        subjectId: str,
        prompt: str,
        check: Any,
        sourceRef: Any,
        dedupPrefix: str = "rsi-regression",
    ) -> Dict[str, str]:
        """C1 例级回归形态 → 逐例转注册（来源钩子）。

        `caseMetrics` 取 RSI 例级回归读数形状
        `{"case_regressions": [caseId, ...], "case_unevidenced": [...]}`；
        只对 `case_regressions`（实测退化例）立案——`case_unevidenced`
        （未量出）不是失败，不立案。每条回归例的 dedupKey =
        `<dedupPrefix>:<subjectId>:<caseId>`。返回 `{caseId: 状态}`；
        无回归例返回空字典（无失败可沉淀，不是错误）。

        subject/prompt/check/sourceRef 由调用方给（只有调用方知道回归例
        守卫的是哪份文本、用什么判据）；subject 仍受 R2 四 subject 体系
        约束，check 仍受判据白名单约束。
        """
        statuses: Dict[str, str] = {}
        regressions: list = []
        if isinstance(caseMetrics, dict):
            raw = caseMetrics.get("case_regressions")
            if isinstance(raw, (list, tuple)):
                regressions = list(raw)
        for caseId in regressions:
            statuses[str(caseId)] = self.registerFailureCase(
                subjectId=subjectId,
                prompt=prompt,
                check=check,
                sourceRef=sourceRef,
                dedupKey=f"{dedupPrefix}:{subjectId}:{caseId}",
            )
        return statuses


def getRatchetSink() -> RatchetSink:
    """进程级单例（DCL + RLock）：评测棘轮在全仓只有一个入口面。"""
    global _SINK
    if _SINK is None:
        with _SINK_LOCK:
            if _SINK is None:
                _SINK = RatchetSink()
    return _SINK


def resetRatchetSink() -> None:
    """清空去重账本（测试隔离用）；不触碰 suite_eval case 注册表本身。"""
    with _DEDUP_LOCK:
        _DEDUP_STORE.clear()


def fromRegression(caseMetrics: Any, **kwargs: Any) -> Dict[str, str]:
    """模块级便捷入口：委托进程级单例 sink（见 `RatchetSink.fromRegression`）。"""
    return getRatchetSink().fromRegression(caseMetrics, **kwargs)
