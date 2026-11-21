# -*- coding: utf-8 -*-
"""MetaEvaluator 元层调参器（P3-2）—— 按世代证据在允许区间内调策略。

设计出处：``docs/04-plans/2026-11-21-recursive-self-evolution-plan.md``
§2.0（自动只发生在判据与边界之内）、§2.1 原则 3（裁判在演化集合之外）、
§3.7（policy.py + meta_evaluator.py 元层设计）、§6 P3 批 P3-2。

职责：从世代账本（``EvolutionGeneration`` 序列，数据源
``NEUROVA_EVOLUTION_GENERATIONS``）计算各候选来源（rsi / eval / external 三路）
的**存活率**（该来源变更所在世代的 G0 影子验证通过率）、**门禁通过率**
（overall 门禁通过率）与**金丝雀期表现**（rolledBack 计数），依据数据在
``EvolutionPolicy`` 的允许区间内产出新策略候选（如某来源存活率显著高 → 上调
其权重；回滚多 → 下调）。数据不足（世代数低于最小门槛 / 无带判据样本）时
如实返回"不调整"并标注 unevidenced，绝不拿 0 样本冒充证据。

边界纪律（裁判件不可达）：新策略候选全部经 ``EvolutionPolicy`` 构造期域校验，
越界即 ``PolicyBoundsError``；权重转移带显式钳制（近上界只调到边界为止）。
调参规则常量（最小世代数 / 步长 / 显著阈 / 上调门槛）是**只读常量**
（forbidden 语义）：策略可以在规则内自我调整，规则本身只能人工 PR 改。

阶段纪律（本卡）：``applyIfApproved`` 一律需要非空 approver（人工批准）；
自动调参留待后续相位解锁。入账走 ``EvolutionPolicyLedger`` 既有纪律
（同号异摘要拒 / 未注册号拒 / 幂等重注册）。

空转件转正：``strategy_comparison.compareStrategies``（三策略对比读数）与
``deployment_amortization.deploymentAmortization``（成本摊销读数）在本模块
接入为 adjustment 的 evidence 证据源——两件从"仅测试消费"转为有生产消费方。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.evolution.rsi.deployment_amortization import deploymentAmortization
from neurova.evolution.rsi.gate_chain import GATE_OVERALL, GATE_SURVIVAL
from neurova.evolution.rsi.gate_verdict import STATE_PASSED, STATE_UNEVIDENCED
from neurova.evolution.rsi.generation_ledger import (
    ChangeRef,
    EvolutionGeneration,
    GenerationStatus,
)
from neurova.evolution.rsi.policy import (
    VALID_SOURCE_KEYS,
    EvolutionPolicy,
    EvolutionPolicyLedger,
    PolicyBoundsError,
)
from neurova.evolution.rsi.strategy_comparison import compareStrategies

logger = get_logger(__name__)

__all__ = [
    "MIN_GENERATIONS_FOR_ADJUSTMENT",
    "WEIGHT_ADJUST_STEP",
    "SIGNIFICANT_SURVIVAL_MARGIN",
    "WINNER_MIN_SURVIVAL_RATE",
    "MetaEvaluator",
    "PolicyAdjustment",
]

# ---------------------------------------------------------------------------
# 调参规则常量（forbidden 语义：只读，无运行时改写接口）。
# ---------------------------------------------------------------------------
#: 触发调参所需的最小世代数（低于即 unevidenced 不调整）。
MIN_GENERATIONS_FOR_ADJUSTMENT = 3
#: 单次权重转移步长（和恒为 1 的转移量）。
WEIGHT_ADJUST_STEP = 0.1
#: 「存活率显著高」的最小领先幅度。
SIGNIFICANT_SURVIVAL_MARGIN = 0.25
#: 参评上调的来源存活率下限（至少过半才谈得上"显著高"）。
WINNER_MIN_SURVIVAL_RATE = 0.5

#: ChangeRef.kind → 候选来源（三路对齐计划书 §2.2：RSI 参数臂 /
#: evolution_eval 文本技能臂 / neuacp 代码臂；kind 词表对齐 shadow_verify）。
_CHANGE_KIND_SOURCE = {
    "parameter": "rsi",
    "text": "eval",
    "promptTemplate": "eval",
    "skillCard": "eval",
    "skill": "eval",
    "patch": "external",
    "code": "external",
}


def _emptyMetric() -> Dict[str, Any]:
    """单来源指标快照骨架（分母 / 分子分开记，unevidenced 不混入分母）。"""
    return {
        "samples": 0,            # 含该来源变更的世代数
        "judged": 0,             # 有 G0 判据的世代数（存活率分母）
        "survived": 0,           # G0 passed 计数
        "survivalUnevidenced": 0,
        "survivalRate": None,    # survived/judged；judged=0 → None（不冒充 0）
        "gateJudged": 0,         # 有 overall 判据的世代数（门禁通过率分母）
        "gatePassed": 0,
        "gateUnevidenced": 0,
        "gatePassRate": None,
        "deployed": 0,
        "rejected": 0,
        "rolledBack": 0,         # 金丝雀期表现：回滚计数
    }


def _fmtWeight(value: Any) -> str:
    return "None" if value is None else f"{float(value):.3f}"


@dataclass(frozen=True)
class PolicyAdjustment:
    """一次策略调参提议（可对账：版本链 + 指标快照 + 证据读数）。

    - ``applied=False, unevidenced=True``：数据不足，不调整（诚实缺证据）；
    - ``applied=False, unevidenced=False``：数据足够但无显著信号 / 边界钳制，
      本轮不调整；
    - ``applied=True``：``proposedPolicy`` 是经构造校验的新策略候选，
      ``applyIfApproved`` 批准后作为新版本入策略台账。
    """

    baseVersion: str
    newVersion: str
    applied: bool
    unevidenced: bool
    reason: str
    proposedPolicy: Optional[EvolutionPolicy]
    sourceMetrics: Dict[str, Dict[str, Any]]
    evidence: Dict[str, Any]

    @property
    def summary(self) -> str:
        """入账摘要（确定性：同数据同摘要，供台账幂等/伪造判定）。"""
        if not self.applied or self.proposedPolicy is None:
            return f"策略不调整（基线 {self.baseVersion or '无'}）: {self.reason}"
        base = self.evidence.get("baseWeights") or {}
        proposed = self.evidence.get("proposedWeights") or {}
        deltas = "；".join(
            f"{key} {_fmtWeight(base.get(key))}→{_fmtWeight(proposed[key])}"
            for key in sorted(proposed)
            if base.get(key) != proposed[key]
        )
        return (
            f"按世代证据调参 {self.baseVersion}→{self.newVersion}（{deltas}）："
            f"{self.reason}"
        )


class MetaEvaluator:
    """元层调参器：世代证据 → 允许区间内的新策略候选 → 人工批准入账。"""

    def __init__(
        self,
        *,
        baseVersion: str = "P_0",
        harness: Optional[Any] = None,
        strategyParamsProvider: Optional[Callable[[], Dict[str, Dict[str, Any]]]] = None,
        usageSnapshotProvider: Optional[Callable[[], Dict[str, Any]]] = None,
        devTokensProvider: Optional[Callable[[], int]] = None,
        amortizationHorizon: int = 100,
    ):
        """
        Args:
            baseVersion: 本评估器产出的调整所基于的策略版本号（新版本号在其上
                递增生成；对账时与策略台账的最新版本对读）。
            harness: 三策略对比用的评分机（``RSIEvalHarness`` 同形，``run``
                返回含 ``score`` 的映射）；缺省惰性构造，失败如实降级。
            strategyParamsProvider: ``{策略名: 活参数态}`` 供给源；缺省＝对比
                读数如实落 unevidenced（不硬算）。
            usageSnapshotProvider: serving 用量快照源（形如
                ``usage_accounting.snapshot()``）；缺省惰性取真单例。
            devTokensProvider: 开发成本 token 数供给源；缺省按 0 记（摊销
                读数只覆盖 serving 段，诚实标注）。
            amortizationHorizon: 摊销视野 N（部署后任务数）。
        """
        self._baseVersion = str(baseVersion)
        self._harness = harness
        self._strategyParamsProvider = strategyParamsProvider
        self._usageSnapshotProvider = usageSnapshotProvider
        self._devTokensProvider = devTokensProvider
        self._amortizationHorizon = int(amortizationHorizon)
        self._harnessLock = threading.Lock()

    # ── 主入口 ────────────────────────────────────────────────

    def evaluateAndPropose(
        self,
        *,
        policy: EvolutionPolicy,
        generations: List[EvolutionGeneration],
    ) -> PolicyAdjustment:
        """按世代史评估各来源表现，产出允许区间内的策略调整提议。"""
        if not isinstance(policy, EvolutionPolicy):
            raise TypeError(
                f"policy 必须是 EvolutionPolicy，实为 {type(policy).__name__}"
            )
        gens = list(generations or [])
        for gen in gens:
            if not isinstance(gen, EvolutionGeneration):
                raise TypeError(
                    f"generations 元素必须是 EvolutionGeneration，实为 "
                    f"{type(gen).__name__}"
                )

        metrics, unattributed = self._sourceMetrics(gens)
        evidence: Dict[str, Any] = {
            "generationCount": len(gens),
            "sourceMetrics": metrics,
            "unattributedChanges": unattributed,
            "strategyComparison": self._strategyComparisonReadout(),
            "deploymentAmortization": self._amortizationReadout(),
        }

        if len(gens) < MIN_GENERATIONS_FOR_ADJUSTMENT:
            return self._noAdjustment(
                metrics, evidence,
                f"世代数 {len(gens)} 低于最小门槛 "
                f"{MIN_GENERATIONS_FOR_ADJUSTMENT}，数据不足不调整",
                unevidenced=True,
            )
        judged = {name: m for name, m in metrics.items() if m["judged"] > 0}
        if not judged:
            return self._noAdjustment(
                metrics, evidence,
                "各来源均无带 G0 判据的世代样本，存活率不可估，不调整",
                unevidenced=True,
            )

        ranked = sorted(
            judged.items(),
            key=lambda kv: (-kv[1]["survivalRate"], kv[1]["rolledBack"], kv[0]),
        )
        # 上调对象：存活率过半且无回滚记录（有回滚的来源不参评上调，安全第一）
        winner = None
        for name, m in ranked:
            if (m["rolledBack"] == 0
                    and m["survivalRate"] >= WINNER_MIN_SURVIVAL_RATE):
                winner = name
                break
        if winner is None:
            return self._noAdjustment(
                metrics, evidence,
                "无可上调来源：存活率达标（≥0.5）且无回滚记录的来源缺席"
                "——有回滚记录的来源不参评上调",
                unevidenced=False,
            )
        others = [kv for kv in ranked if kv[0] != winner]
        if not others:
            return self._noAdjustment(
                metrics, evidence,
                "仅一个来源有判据样本，无对照来源，不调整",
                unevidenced=False,
            )
        winnerRate = judged[winner]["survivalRate"]
        bestOtherRate = max(m["survivalRate"] for _, m in others)
        margin = round(winnerRate - bestOtherRate, 6)
        if margin < SIGNIFICANT_SURVIVAL_MARGIN:
            return self._noAdjustment(
                metrics, evidence,
                f"{winner} 存活率 {winnerRate:.3f} 领先幅度 {margin:.3f} "
                f"不足显著阈 {SIGNIFICANT_SURVIVAL_MARGIN}，证据不足以上调",
                unevidenced=False,
            )
        # 下调对象：对照来源中存活率最低者（并列时回滚多者优先、名字序兜底）
        loser, loserMetric = min(
            others,
            key=lambda kv: (kv[1]["survivalRate"], -kv[1]["rolledBack"], kv[0]),
        )
        return self._proposeWeightTransfer(
            policy, winner, loser, winnerRate, loserMetric, metrics, evidence
        )

    # ── 入账（本卡阶段：一律人工批准） ─────────────────────────

    @staticmethod
    def applyIfApproved(
        adjustment: PolicyAdjustment,
        *,
        approver: str,
        ledger: EvolutionPolicyLedger,
    ) -> bool:
        """审批通过的调整作为新策略版本登记入台账；返回是否入账。

        - approver 为空 → False（本卡阶段调参一律人工批准，自动调参留待后续）；
        - 无候选（unevidenced / 边界钳制不调整）→ False（无可入账）；
        - 同号异摘要 / 同号同摘要异策略 → 台账 ``register`` 抛 ValueError
          （伪造调参当场暴露，不静默吞）。
        """
        if not isinstance(adjustment, PolicyAdjustment):
            raise TypeError(
                f"adjustment 必须是 PolicyAdjustment，实为 "
                f"{type(adjustment).__name__}"
            )
        if not isinstance(ledger, EvolutionPolicyLedger):
            raise TypeError(
                f"ledger 必须是 EvolutionPolicyLedger，实为 {type(ledger).__name__}"
            )
        approverName = str(approver or "").strip()
        if not approverName:
            return False  # 本卡阶段：无人工批准即拒，不做自动调参
        if not adjustment.applied or adjustment.proposedPolicy is None:
            return False  # 无候选可入账
        summary = f"{adjustment.summary}（审批人: {approverName}）"
        ledger.register(adjustment.newVersion, summary, adjustment.proposedPolicy)
        logger.info(
            "策略调参入账: %s -> %s（审批人: %s）",
            adjustment.baseVersion, adjustment.newVersion, approverName,
        )
        return True

    # ── 指标计算 ──────────────────────────────────────────────

    def _sourceMetrics(
        self, gens: List[EvolutionGeneration]
    ) -> tuple:
        """按来源聚合世代指标，返回 ``(metrics, unattributedCount)``。

        判据（verdicts）是世代级的（账本 schema 如此），来源归因按"该世代
        含该来源变更"聚合——不复制影子逐候选明细（与 P0-3 账本契约一致）。
        unevidenced 世代单列计数，不混入通过率分母（不拿缺证据冒充失败）；
        归源失败的变更计入 unattributedCount（随 evidence 留痕，不静默丢）。
        """
        metrics = {source: _emptyMetric() for source in VALID_SOURCE_KEYS}
        unattributed = 0
        for gen in gens:
            sources = set()
            for change in gen.changes:
                source = self._sourceFor(change)
                if source:
                    sources.add(source)
                else:
                    unattributed += 1
            for source in sources:
                m = metrics[source]
                m["samples"] += 1
                survival = gen.verdicts.get(GATE_SURVIVAL)
                if survival is not None:
                    m["judged"] += 1
                    if survival.state == STATE_PASSED:
                        m["survived"] += 1
                    elif survival.state == STATE_UNEVIDENCED:
                        m["survivalUnevidenced"] += 1
                overall = gen.verdicts.get(GATE_OVERALL)
                if overall is not None:
                    m["gateJudged"] += 1
                    if overall.state == STATE_PASSED:
                        m["gatePassed"] += 1
                    elif overall.state == STATE_UNEVIDENCED:
                        m["gateUnevidenced"] += 1
                if gen.status == GenerationStatus.ROLLED_BACK.value:
                    m["rolledBack"] += 1
                elif gen.status == GenerationStatus.REJECTED.value:
                    m["rejected"] += 1
                elif gen.status == GenerationStatus.DEPLOYED.value:
                    m["deployed"] += 1
        for m in metrics.values():
            if m["judged"] > 0:
                m["survivalRate"] = round(m["survived"] / m["judged"], 6)
            if m["gateJudged"] > 0:
                m["gatePassRate"] = round(m["gatePassed"] / m["gateJudged"], 6)
        return metrics, unattributed

    def _sourceFor(self, change: ChangeRef) -> Optional[str]:
        """变更 → 候选来源：kind 词表优先，注册表 layer 兜底，均不中则 None。"""
        kind = str(getattr(change, "kind", "") or "")
        mapped = _CHANGE_KIND_SOURCE.get(kind)
        if mapped:
            return mapped
        try:
            from neurova.evolution.rsi.target_registry import get_target_registry

            target = get_target_registry().get(str(change.targetId))
        except Exception:  # noqa: BLE001 - 注册表缺席/未注册 → 归源失败如实 None
            return None
        if target.layer == "L2":
            return "external"
        if target.layer == "L1" and target.kind in ("promptTemplate", "skillCard"):
            return "eval"
        if target.layer == "L1":
            return "rsi"
        return None

    # ── 权重转移（区间内 + 显式钳制） ──────────────────────────

    def _proposeWeightTransfer(
        self,
        policy: EvolutionPolicy,
        winner: str,
        loser: str,
        winnerRate: float,
        loserMetric: Dict[str, Any],
        metrics: Dict[str, Dict[str, Any]],
        evidence: Dict[str, Any],
    ) -> PolicyAdjustment:
        weights = dict(policy.sourceWeights)
        winnerWeight = float(weights[winner])
        loserWeight = float(weights[loser])
        # 转移量受三重钳制：步长 / 下调方现有权重 / 上调方剩余空间
        delta = min(WEIGHT_ADJUST_STEP, loserWeight, 1.0 - winnerWeight)
        if delta <= 0.0:
            return self._noAdjustment(
                metrics, evidence,
                f"{winner} 权重已在上界或 {loser} 无可转出权重"
                f"（delta={delta:.3f}），钳制不越界，本轮不调整",
                unevidenced=False,
            )
        newWeights = dict(weights)
        newWeights[winner] = winnerWeight + delta
        newWeights[loser] = loserWeight - delta
        # 浮点残差归到上调方后显式钳制到 [0,1]（近上界场景不越界）
        residual = 1.0 - sum(newWeights.values())
        newWeights[winner] = newWeights[winner] + residual
        for key in newWeights:
            newWeights[key] = min(1.0, max(0.0, newWeights[key]))
        try:
            proposed = EvolutionPolicy(
                sourceWeights=newWeights,
                maxTokensPerGeneration=policy.maxTokensPerGeneration,
                maxWallMs=policy.maxWallMs,
                shadowConcurrency=policy.shadowConcurrency,
                canaryWindow=policy.canaryWindow,
                gateThresholds=policy.gateThresholds,
            )
        except PolicyBoundsError as exc:
            # 钳制后仍越界只可能是意外：如实按不调整处理，绝不带病入账
            return self._noAdjustment(
                metrics, evidence,
                f"候选权重越界被构造校验拒绝（{exc}），本轮不调整",
                unevidenced=False,
            )
        reason = (
            f"{winner} 存活率 {winnerRate:.3f} 显著领先"
            f"（步长 {delta:.3f}），{loser} 存活率 "
            f"{loserMetric['survivalRate']:.3f}/回滚 {loserMetric['rolledBack']} 次，"
            f"权重下调"
        )
        evidence = dict(evidence)
        evidence["baseWeights"] = dict(weights)
        evidence["proposedWeights"] = dict(proposed.sourceWeights)
        return PolicyAdjustment(
            baseVersion=self._baseVersion,
            newVersion=self._nextVersion(self._baseVersion),
            applied=True,
            unevidenced=False,
            reason=reason,
            proposedPolicy=proposed,
            sourceMetrics=metrics,
            evidence=evidence,
        )

    def _noAdjustment(
        self,
        metrics: Dict[str, Dict[str, Any]],
        evidence: Dict[str, Any],
        reason: str,
        *,
        unevidenced: bool,
    ) -> PolicyAdjustment:
        return PolicyAdjustment(
            baseVersion=self._baseVersion,
            newVersion="",
            applied=False,
            unevidenced=unevidenced,
            reason=reason,
            proposedPolicy=None,
            sourceMetrics=metrics,
            evidence=evidence,
        )

    @staticmethod
    def _nextVersion(base: str) -> str:
        """P_0 → P_1；无数字尾缀时追加 -1（版本链只增，不重写历史）。"""
        digits = ""
        for ch in reversed(base):
            if ch.isdigit():
                digits = ch + digits
            else:
                break
        if digits:
            head = base[: len(base) - len(digits)]
            return f"{head}{int(digits) + 1}"
        return f"{base}-1"

    # ── 两个空转件的消费面（evidence 证据源） ───────────────────

    def _strategyComparisonReadout(self) -> Dict[str, Any]:
        """三策略同题同机对比读数（compareStrategies 转正消费方一）。"""
        params: Optional[Dict[str, Dict[str, Any]]] = None
        if self._strategyParamsProvider is not None:
            try:
                params = self._strategyParamsProvider()
            except Exception as exc:  # noqa: BLE001 - 参数源失败如实降级
                return {
                    "state": "unevidenced",
                    "reason": f"策略参数源读取失败: {exc}",
                }
        if not params:
            return {
                "state": "unevidenced",
                "reason": "未注入策略参数源（strategyParamsProvider），三策略对比不硬算",
            }
        harness = self._ensureHarness()
        if harness is None:
            return {
                "state": "unevidenced",
                "reason": "评分机缺席，三策略对比不硬算",
            }
        return compareStrategies(params, harness=harness)

    def _amortizationReadout(self) -> Dict[str, Any]:
        """部署摊销读数（deploymentAmortization 转正消费方二）。"""
        usage: Optional[Dict[str, Any]] = None
        if self._usageSnapshotProvider is not None:
            try:
                usage = self._usageSnapshotProvider()
            except Exception as exc:  # noqa: BLE001 - 快照失败如实降级
                return {
                    "state": "unevidenced",
                    "reason": f"usage 快照读取失败: {exc}",
                }
        else:
            try:
                from neurova.core.usage_accounting import get_usage_accounting

                usage = get_usage_accounting().snapshot()
            except Exception as exc:  # noqa: BLE001 - 记账缺席如实降级
                return {
                    "state": "unevidenced",
                    "reason": f"usage 记账缺席: {exc}",
                }
        devTokens = 0
        if self._devTokensProvider is not None:
            try:
                devTokens = int(self._devTokensProvider())
            except Exception:  # noqa: BLE001 - 成本源失败按 0 记（诚实缺省）
                devTokens = 0
        return deploymentAmortization(
            dev_tokens=devTokens,
            horizon=self._amortizationHorizon,
            usage_snapshot=usage or {},
        )

    def _ensureHarness(self) -> Optional[Any]:
        """评分机惰性装配（RSIEvalHarness 确定性、无重依赖；失败如实降级）。"""
        if self._harness is None:
            with self._harnessLock:
                if self._harness is None:
                    try:
                        from neurova.evolution.rsi.eval_harness import RSIEvalHarness

                        self._harness = RSIEvalHarness()
                    except Exception as exc:  # noqa: BLE001 - 评测机缺席不冒充
                        logger.warning(
                            "RSIEvalHarness 装配失败，策略对比读数将落 unevidenced: %s",
                            exc,
                        )
                        return None
        return self._harness
