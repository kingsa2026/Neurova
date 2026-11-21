"""世代编排器（P1-3）—— 把 RSI 迭代接进「世代账本 + 门禁链 + 影子验证」。

设计出处：docs/04-plans/2026-11-21-recursive-self-evolution-plan.md
§2.0 总体纲要、§2.2 架构总图（GenerationOrchestrator 枢纽）、§2.3 世代模型、
§3.4 gate_chain / §3.5 shadow_verify 的接线、§6 P1 批 P1-3。

职责（§2.2）：一次 RSI 迭代 → 一个世代。围绕 RSIOrchestrator 的优化建议
产出（run_iteration 的 optimizations 与人工批准通道 applyApprovedOptimizations）
挂接世代生命周期::

    openGeneration(proposed，signals=反馈信号摘要，changes=候选→targetId，
                   basisCommit=git HEAD 短 hash)
      → 影子验证（ShadowVerify，逐候选隔离子进程；L1 参数走参数覆盖路径）
      → GateChain.run：G0 存活（影子判据）→ G1 契约（守卫子集，复用探针判据
        数据）→ G2 业务（eval_harness 决策档 A/B，复用 R1 测量机）→
        G3 回归（与父代基线例级 A/B 零退化）→ 落账 gated
      → G0/门禁不过 → markRejected（影子失败候选自动淘汰，总纲）
      → 裁决（按 TargetRegistry.gateLevel：approval 记审批人；auto 全绿自动放行）
      → 人工批准（applyApprovedOptimizations 挂接点）→ canary
      → 应用落地 → 开启金丝雀观测窗（P1-4：观测窗内参数已应用，受限发布）
      → 窗满无异常 → markDeployed（promotedAt 落定）
      → 窗内检查点命中 should_rollback / 健康越界 → 自动回滚（恢复 R1 参数
        快照 + markRolledBack(restoredTo=parentNo) + 留痕原因，无人工确认）
      → markRolledBack（部署后回滚留档）

金丝雀观测窗（P1-4，详案 §2.0/§3.9/§5 L4-L5/§8-4）：世代过门禁且裁决为晋升后
不立即 markDeployed——先进入 canary 态并记录窗口起点；窗长读
``resolveRsiCanaryWindowSeconds()``（默认 300s，测试可经构造参数注入小值/0）。
窗内由既有 ``rollback_manager.should_rollback`` 判据观测（每轮 RSI 迭代即一个
检查点，见 ``observeOpenCanaries``），另可注入健康读数回调消费
``rsi_canary_rollback_thresholds``（当前无生产错误率信号源，默认 None 不参与
判定——诚实预留，不造假信号）。

phase 1 手动档语义不变：世代管线只做记录与验证，实际参数应用仍走 R1 的
人工批准端点；本件不改变应用触发条件——人工批准仍是应用的第一触发，
世代门禁只对「已接管线且门禁未通过」的轮次加一道诚实拒绝（409），
无世代档案时零行为变化（向后兼容）。

失败诚实（fail-soft）：影子验证/门禁任何异常不阻断 RSI 迭代本身，也不影响
生产 chat 链路——开代失败留 ``lastPipelineError`` 告警；影子执行崩溃的候选
按 failed 判据入账（fail-closed，不冒充通过）；被拒世代 markRejected 留档。
"""

from __future__ import annotations

import copy
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.evolution.rsi.gate_chain import (
    GATE_BUSINESS,
    GATE_CONTRACT,
    GATE_DOCTRINE,
    GATE_OVERALL,
    GATE_REGRESSION,
    GATE_SURVIVAL,
    GateChain,
    aggregateGateState,
)
from neurova.evolution.rsi.gate_verdict import (
    STATE_FAILED,
    GateVerdict,
)
from neurova.evolution.rsi.generation_ledger import (
    ChangeRef,
    DecisionRef,
    DeploymentRef,
    EvolutionGeneration,
    GenerationLedger,
    GenerationStatus,
    SignalRef,
)
from neurova.evolution.rsi.orchestrator import RSIManualApplyError
from neurova.evolution.rsi.shadow_verify import (
    KIND_PARAMETER,
    ShadowChange,
    ShadowRunResult,
    ShadowVerify,
)
from neurova.evolution.rsi.survival_probe import CRITERION_GUARD, CRITERION_ORDER
from neurova.evolution.rsi.target_registry import (
    EvolutionTargetRegistry,
    get_target_registry,
)

logger = get_logger(__name__)

__all__ = ["GenerationOrchestrator", "gitHeadShort"]

#: RSI 参数族候选的注册表 targetId（首批 approval 档，单一事实源在 target_registry）。
RSI_PARAMETER_FAMILY_TARGET = "rsi.parameterFamily"

#: 影子验证隔离数据根的目录名前缀（shadow_verify 的 tempfile.mkdtemp 约定）——
#: 用毕回收只认这个前缀，防止误删测试桩/其它目录。
_SHADOW_ROOT_PREFIX = "neurovaShadow-"

#: 影子结论里属于「应用判据」的键（随 G0 计：候选连应用都落不了即没资格参评）。
_APPLY_VERDICT_KEYS = ("parameterApply", "patchApply", "shadowRun")

#: 影子结论里业务/回归判据的键（businessCriteria 回调产出，G2/G3 数据源）。
_BUSINESS_VERDICT_KEY = "g2Business"
_REGRESSION_VERDICT_KEY = "g3Regression"


def gitHeadShort() -> str:
    """当前 git HEAD 短 hash（世代 basisCommit 的可复现冻结用）。

    取不到（非 git 环境/命令缺失）时如实落 ``unknown``，不编造哈希。
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if proc.returncode == 0:
            head = proc.stdout.strip()
            if head:
                return head
    except Exception:  # noqa: BLE001 - 取不到就如实说 unknown，不阻断
        pass
    return "unknown"


def _applyOverridesToSnapshot(
    liveParams: Dict[str, Dict[str, Any]],
    overrides: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """把候选参数覆盖代入活值快照的**深拷贝**（system→{param:value}，与候选生成同形）。"""
    snapshot = copy.deepcopy(liveParams)
    for system, params in (overrides or {}).items():
        snapshot.setdefault(str(system), {}).update(dict(params or {}))
    return snapshot


def _aggregateGateVerdict(gateKey: str, verdicts: List[GateVerdict]) -> GateVerdict:
    """一道门禁的判据集聚合为单条三态结论（聚合单源 ``aggregateGateState``，
    世代账本的 verdicts 映射每门只存一条）。"""
    state = aggregateGateState(verdicts)
    reasons = [v.reason for v in verdicts if v.reason]
    headline = "；".join(reasons[:4]) + ("…" if len(reasons) > 4 else "")
    return GateVerdict.of(
        state,
        f"{gateKey} 聚合 {len(verdicts)} 条判据为 {state}：{headline}",
        {"gate": gateKey, "count": len(verdicts), "states": [v.state for v in verdicts]},
    )


class GenerationOrchestrator:
    """世代编排器：提案 → 影子验证 → 门禁链 → 裁决 → 部署/拒绝（§2.2 枢纽）。

    挂接方式（最小侵入）：RSIOrchestrator 持有本件**可选引用**
    （``orchestrator.generationOrchestrator``，默认 None 时 RSI 行为零变化）；
    生产装配点在 ``agent_wiring.wireAgentRsi``。本件不重构 run_iteration 主体，
    挂接点：建议产出点（``onRoundProposals``）、人工批准通道
    （``gateManualApproval`` / ``onManualApprovalApplied``）、自动档应用落地
    （``onAutoApplyOutcome``）与每轮迭代的金丝雀观测驱动
    （``observeOpenCanaries``，P1-4）。
    """

    def __init__(
        self,
        *,
        rsiOrchestrator: Optional[Any] = None,
        ledger: Optional[GenerationLedger] = None,
        registry: Optional[EvolutionTargetRegistry] = None,
        shadowVerify: Optional[Any] = None,
        canaryWindowSeconds: Optional[float] = None,
        canaryHealthCallback: Optional[Callable[[], Optional[Dict[str, Any]]]] = None,
    ):
        """
        Args:
            rsiOrchestrator: RSI 编排器回引（G2/G3 判据取活值快照用；缺席时
                业务/回归判据如实落 unevidenced，不冒充通过）。
            ledger: 世代账本（缺省按 env ``NEUROVA_EVOLUTION_GENERATIONS`` 解析，
                未配置纯内存零 IO）。
            registry: 演化对象注册表（缺省取模块级单例）。
            shadowVerify: 影子验证执行器（缺省惰性构造，注入本件的业务判据回调）。
            canaryWindowSeconds: 金丝雀观测窗长（秒）的测试注入口；None＝读治理
                设置 ``resolveRsiCanaryWindowSeconds()``（决策时刻读取，默认 300s）。
                0＝窗即刻满足（批准应用后直接晋升）。
            canaryHealthCallback: 窗内健康读数回调（P1-4 阈值消费的可注入面）。
                返回 ``{"error_rate": x, "success_rate": y, "baseline_success_rate": z}``
                或 None；缺省 None＝阈值不参与判定（当前无生产错误率信号源，
                诚实预留，不造假信号）。
        """
        self._rsi = rsiOrchestrator
        self._ledger = ledger if ledger is not None else GenerationLedger()
        self._registry = registry if registry is not None else get_target_registry()
        self._shadowVerify = shadowVerify
        self._canaryWindowSeconds = canaryWindowSeconds
        self._canaryHealthCallback = canaryHealthCallback
        self._lock = threading.RLock()
        self._roundGenerations: Dict[int, EvolutionGeneration] = {}
        self._roundChanges: Dict[int, List[ShadowChange]] = {}
        self._roundShadow: Dict[int, Dict[str, ShadowRunResult]] = {}
        # P1-4：开着的金丝雀观测窗，按 RSI 轮次索引。
        # 值：{generationNo, startedMonotonic, startedAtIso, windowSeconds,
        #      snapshot(应用前参数快照，回滚恢复源), parentNo}
        self._canaryWindows: Dict[int, Dict[str, Any]] = {}
        self._evalHarness: Optional[Any] = None
        #: 最近一次管线故障的诚实留痕（开代失败不阻断迭代，但必须可见）。
        self.lastPipelineError: Optional[str] = None

    # ── 读面 ──────────────────────────────────────────────────

    def generationForRound(self, roundNo: int) -> Optional[EvolutionGeneration]:
        """按 RSI 迭代轮次取世代档案（无则 None——查询面不抛）。"""
        with self._lock:
            return self._roundGenerations.get(int(roundNo))

    def generationLedger(self) -> GenerationLedger:
        """只读访问器：世代账本（P1-5 治理读面 GET /rsi/generations* 的数据源）。

        账本在本件构造时必装配（缺省按 env 解析，未配置纯内存零 IO），
        本访问器只暴露读取入口，不新增状态。
        """
        return self._ledger

    # ── 挂接点 1：run_iteration 建议产出点 ────────────────────

    def onRoundProposals(
        self,
        *,
        roundNo: int,
        feedbackSignals: Dict[str, Any],
        optimizations: List[Dict[str, Any]],
        convergenceStatus: str = "",
    ) -> Optional[EvolutionGeneration]:
        """一次 RSI 迭代 → 一个世代：开代 + 影子验证 + 门禁链落账。

        由 run_iteration 的建议产出点调用；本方法自身 fail-soft（任何异常
        记入 ``lastPipelineError`` 并返回 None），不阻断迭代主体。
        """
        if not optimizations:
            return None  # 空轮无候选，不开代（没有「改了什么」可记）
        try:
            with self._lock:
                return self._openAndShadow(
                    int(roundNo), feedbackSignals, optimizations, convergenceStatus
                )
        except Exception as exc:  # noqa: BLE001 - 管线故障不阻断迭代，但必须留痕
            self.lastPipelineError = (
                f"round {roundNo}: {type(exc).__name__}: {exc}"
            )
            logger.warning("世代管线开代失败（不阻断迭代）: %s", self.lastPipelineError)
            return None

    def _openAndShadow(
        self,
        roundNo: int,
        feedbackSignals: Dict[str, Any],
        optimizations: List[Dict[str, Any]],
        convergenceStatus: str,
    ) -> EvolutionGeneration:
        signals = self._summarizeSignals(feedbackSignals, convergenceStatus)
        changes = [self._changeRefFor(opt) for opt in optimizations]
        shadowChanges = [
            self._shadowChangeFor(opt, roundNo, index)
            for index, opt in enumerate(optimizations)
        ]
        gen = self._ledger.openGeneration(
            parentNo=self._parentNo(),
            signals=signals,
            changes=changes,
            basisCommit=gitHeadShort(),
        )
        self._roundGenerations[roundNo] = gen
        self._roundChanges[roundNo] = shadowChanges

        # 影子验证：逐候选隔离执行（L1 参数走参数覆盖路径），按门禁归桶。
        shadowByChange: Dict[str, ShadowRunResult] = {}
        survivalVerdicts: List[GateVerdict] = []
        contractVerdicts: List[GateVerdict] = []
        businessVerdicts: List[GateVerdict] = []
        regressionVerdicts: List[GateVerdict] = []
        for change in shadowChanges:
            result = self._verifyChange(gen, change)
            shadowByChange[change.changeId] = result
            for name, verdict in result.verdicts.items():
                if name == CRITERION_GUARD:
                    # 守卫子集归 G1 契约门（复用 survival_probe 的守卫判据数据）
                    contractVerdicts.append(verdict)
                elif name == _BUSINESS_VERDICT_KEY:
                    businessVerdicts.append(verdict)
                elif name == _REGRESSION_VERDICT_KEY:
                    regressionVerdicts.append(verdict)
                elif name in CRITERION_ORDER or name in _APPLY_VERDICT_KEYS:
                    survivalVerdicts.append(verdict)
        self._roundShadow[roundNo] = shadowByChange

        # 门禁链（§3.4）：G0 存活 → G1 契约 → G2 业务 → G3 回归
        # （G4 教义门仅 L2 代码态，L1 缺席不出键）。
        chain = GateChain().run(
            survivalVerdicts=survivalVerdicts,
            contractVerdicts=contractVerdicts or None,
            businessVerdicts=businessVerdicts or None,
            regressionVerdicts=regressionVerdicts or None,
        )
        self._recordChainVerdicts(gen, chain)
        overall = (
            chain.get(GATE_OVERALL)
            or [GateVerdict.unevidenced("门禁链未产出 overall 结论")]
        )[0]
        if not overall:
            # 门禁不过 → 世代自动拒绝（总纲：跑不通不落基线），留档可归因；
            # 影子失败在此短路（G0 failed 时 chain 只有 g0/overall）。
            self._ledger.markRejected(gen.generationNo, overall.reason)
        elif self._decisionKindFor(roundNo) == "auto":
            # auto 档（当前注册表首批无）：门禁全绿即自动放行进入金丝雀——
            # P1-4 起晋升不再在开代时落定：参数应用落地后开启观测窗
            # （onAutoApplyOutcome），窗满无异常才 markDeployed。
            self._ledger.recordDecision(gen.generationNo, DecisionRef(kind="auto"))
        self._cleanupShadowRoots(roundNo)
        return self._ledger.get(gen.generationNo)

    def _verifyChange(self, gen: EvolutionGeneration, change: ShadowChange) -> ShadowRunResult:
        """单候选影子验证（隔离子进程）；执行崩溃 = 该候选没跑成，fail-closed 记 failed。"""
        try:
            return self._shadow().verify(change)
        except Exception as exc:  # noqa: BLE001 - 影子执行异常按 failed 判据入账
            self.lastPipelineError = (
                f"generation {gen.generationNo} shadow {change.changeId}: "
                f"{type(exc).__name__}: {exc}"
            )
            logger.warning(
                "世代 %s 影子验证异常（changeId=%s）: %s",
                gen.generationNo, change.changeId, exc,
            )
            return ShadowRunResult(
                changeId=change.changeId,
                kind=change.kind,
                verdicts={
                    "shadowRun": GateVerdict.failed(
                        f"影子验证执行异常: {exc}",
                        evidence={"changeId": change.changeId},
                    )
                },
                overall=STATE_FAILED,
                durationMs=0,
                dataRoot="",
                workspace="",
            )

    # ── 挂接点 2：applyApprovedOptimizations 人工批准通道 ─────

    def gateManualApproval(
        self, *, roundNo: int, approvedBy: str
    ) -> Optional[EvolutionGeneration]:
        """人工批准前的世代门禁：门禁未通过的世代拒绝应用（参数不落地）。

        - 本轮无世代档案（开代失败/未挂接）→ 放行（不因管线缺席卡死人工通道）；
        - 世代已被拒（影子失败/门禁未过）→ 409；
        - gated（门禁全绿待裁决）→ 记裁决（approval 档记审批人）→ canary；
        - canary（已裁决、上次应用中断的重试）→ 放行，不重复裁决。
        """
        gen = self.generationForRound(roundNo)
        if gen is None:
            return None
        if gen.status == GenerationStatus.REJECTED.value:
            reason = gen.decision.reason if gen.decision is not None else "门禁未通过"
            raise RSIManualApplyError(
                f"世代 {gen.generationNo} 已被门禁拒绝，参数不应用：{reason}", 409
            )
        if gen.status == GenerationStatus.CANARY.value:
            return gen
        if gen.status != GenerationStatus.GATED.value:
            raise RSIManualApplyError(
                f"世代 {gen.generationNo} 门禁未完成（status={gen.status}），暂不可批准应用",
                409,
            )
        self._ledger.recordDecision(gen.generationNo, self._decisionFor(roundNo, approvedBy))
        return self._ledger.get(gen.generationNo)

    def onManualApprovalApplied(
        self, *, roundNo: int, approvedBy: str, outcome: Dict[str, Any]
    ) -> Optional[EvolutionGeneration]:
        """应用段落定后的部署挂接（P1-4）：应用落地 → 开金丝雀观测窗；
        回滚/未落地 → markRejected。晋升改由窗满检查点落定。"""
        return self._settlePostApply(
            roundNo, outcome, channel="人工批准",
            channelNote=f"approved_by={approvedBy}",
        )

    def onAutoApplyOutcome(
        self, *, roundNo: int, outcome: Dict[str, Any]
    ) -> Optional[EvolutionGeneration]:
        """自动档应用段落定后的部署挂接（P1-4）：与人工通道同一套观测窗语义。"""
        return self._settlePostApply(roundNo, outcome, channel="自动档", channelNote="")

    def _settlePostApply(
        self,
        roundNo: int,
        outcome: Dict[str, Any],
        *,
        channel: str,
        channelNote: str,
    ) -> Optional[EvolutionGeneration]:
        """应用段落定共通处理：落地 → 开观测窗；回滚/未落地 → 拒绝留档。

        金丝雀＝受限发布：观测窗内参数**已应用**（非影子重跑）。窗口起点在
        此刻记录；恢复源取 R1 应用段的应用前参数快照（``_lastPreApplySnapshot``，
        R1 在每次应用前自拍），不另造第二份快照。
        """
        gen = self.generationForRound(roundNo)
        if gen is None:
            return None
        if outcome.get("rolled_back"):
            self._ledger.markRejected(
                gen.generationNo, f"{channel}应用段触发回滚判据，世代淘汰（未部署）"
            )
        elif int(outcome.get("applied_count") or 0) >= 1 and (
            gen.status == GenerationStatus.CANARY.value
        ):
            if int(roundNo) in self._canaryWindows:
                return gen  # 应用中断重试：窗口已在观测，不重复开窗
            self._openCanaryWindow(int(roundNo), gen)
        elif gen.status == GenerationStatus.CANARY.value:
            self._ledger.markRejected(
                gen.generationNo,
                f"{channel}后应用未落地（applied_count={outcome.get('applied_count')}）",
            )
        return self._ledger.get(gen.generationNo)

    # ── P1-4：金丝雀观测窗与自动回滚 ──────────────────────────

    def _resolveCanaryWindowSeconds(self) -> float:
        """观测窗长：测试注入值优先，否则决策时刻读治理设置（活旋钮，不缓存）。"""
        if self._canaryWindowSeconds is not None:
            return float(self._canaryWindowSeconds)
        from neurova.security.governance_settings import resolveRsiCanaryWindowSeconds

        return float(resolveRsiCanaryWindowSeconds())

    def _openCanaryWindow(
        self, roundNo: int, gen: EvolutionGeneration
    ) -> None:
        """开启观测窗并记录起点（参数已应用）；窗长 0 视为即刻满足，直接晋升。"""
        windowSeconds = self._resolveCanaryWindowSeconds()
        startedAtIso = datetime.now(timezone.utc).isoformat()
        snapshot: Dict[str, Any] = {}
        if self._rsi is not None:
            snapshot = dict(getattr(self._rsi, "_lastPreApplySnapshot", None) or {})
        self._canaryWindows[int(roundNo)] = {
            "generationNo": gen.generationNo,
            "startedMonotonic": time.monotonic(),
            "startedAtIso": startedAtIso,
            "windowSeconds": float(windowSeconds),
            "snapshot": snapshot,
            "parentNo": gen.parentNo,
        }
        try:
            self._ledger.annotateCanaryWindow(gen.generationNo, startedAtIso)
        except Exception as exc:  # noqa: BLE001 - 注记失败不阻断观测，但必须留痕
            self.lastPipelineError = (
                f"generation {gen.generationNo} canary annotate: "
                f"{type(exc).__name__}: {exc}"
            )
            logger.warning(
                "世代 %s 观测窗起点落账失败（观测继续，但结算对账缺起点）: %s",
                gen.generationNo, exc,
            )
        logger.info(
            "世代 %s 金丝雀观测窗开启（round=%s 窗长=%.1fs 参数已应用）",
            gen.generationNo, roundNo, windowSeconds,
        )
        if windowSeconds <= 0:
            # 窗长 0：观测窗即刻满足（演练一）——无需等待检查点，直接晋升。
            self._promoteCanary(int(roundNo), self._canaryWindows[int(roundNo)], gen)

    def canaryCheckpoint(
        self, roundNo: int, readings: Optional[Dict[str, Any]] = None
    ) -> Optional[EvolutionGeneration]:
        """金丝雀观测检查点：窗内判据观测；越界自动回滚，窗满晋升。

        - 检查点命中 ``rollback_manager.should_rollback``（读数由调用方/迭代
          驱动注入）或健康阈值越界 → **全自动回滚**（恢复 R1 应用前参数快照
          + markRolledBack(restoredTo=parentNo) + 留痕原因，无人工确认，总纲）；
        - 窗满且无异常 → markDeployed（promotedAt 落定）；
        - 窗未满且判据未命中 → 保持 canary；
        - 该轮无开窗（未开代/已结算）→ 幂等返回当前世代档案。
        """
        with self._lock:
            return self._canaryCheckpointLocked(roundNo, readings)

    def _canaryCheckpointLocked(
        self, roundNo: int, readings: Optional[Dict[str, Any]]
    ) -> Optional[EvolutionGeneration]:
        window = self._canaryWindows.get(int(roundNo))
        if window is None:
            return self.generationForRound(roundNo)
        gen = self._ledger.get(window["generationNo"])
        if gen is None or gen.status != GenerationStatus.CANARY.value:
            # 窗口对应的世代已不在观测态（外部处置/重启后账本回放）：关窗防漏。
            self._canaryWindows.pop(int(roundNo), None)
            return gen
        reason = self._canaryRollbackReason(readings)
        if reason:
            return self._executeCanaryRollback(int(roundNo), window, gen, reason)
        elapsed = time.monotonic() - window["startedMonotonic"]
        if elapsed >= window["windowSeconds"]:
            return self._promoteCanary(int(roundNo), window, gen)
        return gen

    def observeOpenCanaries(
        self, readings: Optional[Dict[str, Any]] = None
    ) -> List[EvolutionGeneration]:
        """观测全部开窗世代（生产驱动：RSI 每轮迭代调用一次，fail-soft 由调用方兜）。

        ``readings`` 是本轮迭代的健康读数（gain/gain_ci/e2e_gain/
        case_regressions/convergence_status/roi），喂给每个开窗世代的
        should_rollback 判据——金丝雀窗内参数已应用，后续迭代的实测读数
        就是窗内观测信号。
        """
        settled: List[EvolutionGeneration] = []
        with self._lock:
            rounds = sorted(self._canaryWindows.keys())
        for roundNo in rounds:
            result = self.canaryCheckpoint(roundNo, readings)
            if result is not None:
                settled.append(result)
        return settled

    def canaryReadout(self) -> Dict[str, Any]:
        """开窗观测面（get_status 呈报用）：哪几代在观测、观测了多久。"""
        with self._lock:
            windows = []
            for roundNo, window in sorted(self._canaryWindows.items()):
                gen = self._ledger.get(window["generationNo"])
                windows.append(
                    {
                        "roundNo": roundNo,
                        "generationNo": window["generationNo"],
                        "status": gen.status if gen is not None else "unknown",
                        "windowSeconds": window["windowSeconds"],
                        "elapsedSeconds": round(
                            time.monotonic() - window["startedMonotonic"], 3
                        ),
                        "startedAt": window["startedAtIso"],
                    }
                )
            return {"openWindows": windows, "count": len(windows)}

    def _canaryRollbackReason(
        self, readings: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        """窗内回滚判据：先健康阈值（可注入回调），再 should_rollback 单源。

        返回 None＝继续观测；返回字符串＝回滚原因（留痕进 canaryConclusion）。
        """
        if self._canaryHealthCallback is not None:
            try:
                health = self._canaryHealthCallback()
            except Exception as exc:  # noqa: BLE001 - 健康读数失败不造假、如实降级
                logger.warning("金丝雀健康回调执行失败（阈值判据跳过本轮）: %s", exc)
                health = None
            if isinstance(health, dict):
                thresholds = self._canaryThresholds()
                errorRate = health.get("error_rate")
                if isinstance(errorRate, (int, float)) and not isinstance(errorRate, bool):
                    if float(errorRate) > thresholds["max_error_rate"]:
                        return (
                            f"金丝雀健康越界: error_rate={errorRate} > "
                            f"max_error_rate={thresholds['max_error_rate']}"
                        )
                success = health.get("success_rate")
                baseline = health.get("baseline_success_rate")
                if (
                    isinstance(success, (int, float)) and not isinstance(success, bool)
                    and isinstance(baseline, (int, float)) and not isinstance(baseline, bool)
                ):
                    drop = float(baseline) - float(success)
                    if drop > thresholds["min_success_rate_drop"]:
                        return (
                            f"金丝雀健康越界: success_rate 较基线下降 {drop:.4f} > "
                            f"min_success_rate_drop={thresholds['min_success_rate_drop']}"
                        )
        metrics = dict(readings or {})
        if not metrics:
            return None
        manager = self._rollbackManager()
        if manager is None:
            return None
        if manager.should_rollback(metrics):
            hit = [
                f"{key}={metrics[key]}"
                for key in ("convergence_status", "roi", "gain", "e2e_gain")
                if key in metrics
            ]
            if isinstance(metrics.get("case_regressions"), list) and metrics["case_regressions"]:
                hit.append(f"case_regressions={metrics['case_regressions'][:4]}")
            return f"金丝雀观测命中回滚判据(should_rollback): {'；'.join(hit)}"
        return None

    @staticmethod
    def _canaryThresholds() -> Dict[str, float]:
        """回滚阈值族唯一读法（governance_settings.resolveRsiCanaryRollbackThresholds）。"""
        from neurova.security.governance_settings import (
            resolveRsiCanaryRollbackThresholds,
        )

        return resolveRsiCanaryRollbackThresholds()

    def _rollbackManager(self):
        """should_rollback 判据的单一事实源：优先 RSI 编排器手上的那只。"""
        if self._rsi is not None:
            manager = getattr(self._rsi, "rollback_manager", None)
            if manager is not None:
                return manager
        if getattr(self, "_fallbackRollbackManager", None) is None:
            from neurova.evolution.rsi.rollback_manager import RSIRollbackManager

            self._fallbackRollbackManager = RSIRollbackManager()
        return self._fallbackRollbackManager

    def _executeCanaryRollback(
        self,
        roundNo: int,
        window: Dict[str, Any],
        gen: EvolutionGeneration,
        reason: str,
    ) -> EvolutionGeneration:
        """窗内越界 → 全自动回滚（无人工确认）：恢复 R1 应用前快照 + 留档。

        恢复路径复用 R1 的 ``_restore_optimizable``；rollback_manager 的
        create_snapshot/execute_rollback 留痕（阶段晋升判据"距上次回滚天数"
        的唯一数据源，工单 004）。回滚后该世代终止，下一代以恢复后的基线为父。
        """
        self._canaryWindows.pop(int(roundNo), None)
        snapshot = window.get("snapshot") or {}
        if self._rsi is not None and snapshot:
            snapshotId = self._rsi.rollback_manager.create_snapshot(snapshot)
            self._rsi._restore_optimizable(snapshot)
            if not self._rsi.rollback_manager.execute_rollback(snapshotId):
                logger.error(
                    "金丝雀回滚已执行但 rollback_manager 留痕失败（snapshot_id=%s）",
                    snapshotId,
                )
        parentNo = window.get("parentNo")
        if parentNo is None:
            # 根代无父代世代可指认：诚实走拒绝留痕，不伪装 rolledBackTo。
            logger.warning(
                "世代 %s 金丝雀越界但无父代可回滚（根代），按拒绝留档: %s",
                gen.generationNo, reason,
            )
            self._ledger.markRejected(
                gen.generationNo, f"金丝雀观测越界且无父代可回滚（根代）：{reason}"
            )
        else:
            logger.warning(
                "世代 %s 金丝雀观测越界，自动回滚至父代 %s: %s",
                gen.generationNo, parentNo, reason,
            )
            self._ledger.markRolledBack(
                gen.generationNo, restoredTo=int(parentNo), reason=reason
            )
        return self._ledger.get(gen.generationNo)

    def _promoteCanary(
        self, roundNo: int, window: Dict[str, Any], gen: EvolutionGeneration
    ) -> EvolutionGeneration:
        """窗满无异常 → 晋升生产（markDeployed，promotedAt 落定）。"""
        self._canaryWindows.pop(int(roundNo), None)
        self._ledger.markDeployed(
            gen.generationNo,
            DeploymentRef(
                canaryConclusion=(
                    f"金丝雀观测窗通过（{window['windowSeconds']:.1f}s 无越界），晋升生产"
                )
            ),
        )
        logger.info("世代 %s 金丝雀观测窗通过，晋升生产", gen.generationNo)
        return self._ledger.get(gen.generationNo)

    def markRolledBack(
        self, generationNo: int, restoredTo: int, reason: str = ""
    ) -> None:
        """部署后回滚留档（deployed/canary → rolledBack，记录回滚落点）。

        金丝雀窗内越界的自动回滚（P1-4）多经 ``canaryCheckpoint`` 走
        ``_executeCanaryRollback``（带恢复动作）；本方法保留为显式留痕入口。
        """
        self._ledger.markRolledBack(generationNo, restoredTo, reason=reason)

    # ── 世代要素构建 ──────────────────────────────────────────

    def _summarizeSignals(
        self, feedbackSignals: Dict[str, Any], convergenceStatus: str
    ) -> List[SignalRef]:
        """本轮反馈信号摘要（为什么改）：只收有证据的系统，占位替身不冒充信号。"""
        refs: List[SignalRef] = []
        for system, signals in (feedbackSignals or {}).items():
            if not isinstance(signals, dict):
                continue
            verdict = signals.get("verdict")
            if isinstance(verdict, dict) and verdict.get("state") == "unevidenced":
                continue  # 缺席闭环系统的占位替身：无证据，不进信号
            bits = []
            for key in ("performance_score", "success_rate", "avg_success_rate", "stability"):
                value = signals.get(key)
                if isinstance(value, (int, float)):
                    bits.append(f"{key}={float(value):.3f}")
            refs.append(
                SignalRef(
                    kind="feedback",
                    ref=str(system),
                    summary="; ".join(bits) or "无量化读数",
                )
            )
        refs.append(
            SignalRef(
                kind="convergence",
                ref="convergence",
                summary=f"status={convergenceStatus or 'unknown'}",
            )
        )
        return refs

    def _changeRefFor(self, optimization: Dict[str, Any]) -> ChangeRef:
        parameter = str(optimization.get("parameter") or "")
        return ChangeRef(
            targetId=self._targetIdFor(optimization),
            kind="parameter",
            ref=f"{parameter}: {optimization.get('current_value')} -> {optimization.get('new_value')}",
            rationale=str(optimization.get("reason") or "RSI 棘轮候选步进（setpoint 梯度）"),
        )

    def _targetIdFor(self, optimization: Dict[str, Any]) -> str:
        """优化建议 → 注册表 targetId（单一事实源在注册表）。

        当前候选生成只产 L1 参数族候选（generate_optimizations 只遍历
        OPTIMIZABLE_PARAMETERS），统一映射 rsi.parameterFamily；文本/技能
        候选接入时按 kind 扩展映射。
        """
        try:
            return self._registry.get(RSI_PARAMETER_FAMILY_TARGET).targetId
        except Exception:  # noqa: BLE001 - 注册表缺席/未注册 → 保留字面 id 可追溯
            return RSI_PARAMETER_FAMILY_TARGET

    def _shadowChangeFor(
        self, optimization: Dict[str, Any], roundNo: int, index: int
    ) -> ShadowChange:
        """优化建议 → 影子验证候选（L1 参数覆盖路径）。"""
        system = str(optimization.get("system") or "")
        parameter = str(optimization.get("parameter") or "")
        paramName = parameter.split(".", 1)[1] if "." in parameter else parameter
        newValue = optimization.get("new_value")
        overrides = (
            {system: {paramName: newValue}}
            if (system and paramName and newValue is not None)
            else {}
        )
        return ShadowChange(
            changeId=f"gen-r{roundNo}-{index + 1}",
            kind=KIND_PARAMETER,
            targetId=self._targetIdFor(optimization),
            parameterOverrides=overrides,
        )

    def _parentNo(self) -> Optional[int]:
        """父代 = 当前生产基线（上一部署代）；尚无部署为 None（根代）。"""
        baseline = self._ledger.currentBaseline()
        return baseline.generationNo if baseline is not None else None

    def _decisionKindFor(self, roundNo: int) -> str:
        """按本轮变更涉及对象的注册表 gateLevel 出裁决类型：
        全部 auto → auto；其余（含注册表查不到的保守情形）→ approval。"""
        gateLevels = set()
        for change in self._roundChanges.get(int(roundNo), []):
            try:
                gateLevels.add(self._registry.get(change.targetId).gateLevel)
            except Exception:  # noqa: BLE001 - 查不到按人工档处理（保守）
                gateLevels.add("approval")
        if gateLevels and gateLevels == {"auto"}:
            return "auto"
        return "approval"

    def _decisionFor(self, roundNo: int, approvedBy: str) -> DecisionRef:
        if self._decisionKindFor(roundNo) == "auto":
            return DecisionRef(kind="auto")
        return DecisionRef(kind="approval", approver=str(approvedBy or ""))

    # ── 门禁链落账 ────────────────────────────────────────────

    def _recordChainVerdicts(
        self, gen: EvolutionGeneration, chain: Dict[str, List[GateVerdict]]
    ) -> None:
        """门禁链结论落账（账本状态机合法全路径：首落 g0 → shadowTesting，
        其余门禁+overall 一并落账 → gated）。"""
        aggregated: Dict[str, GateVerdict] = {}
        for gateKey in (GATE_SURVIVAL, GATE_CONTRACT, GATE_BUSINESS, GATE_REGRESSION, GATE_DOCTRINE):
            verdicts = chain.get(gateKey) or []
            if verdicts and gateKey not in gen.verdicts:
                aggregated[gateKey] = _aggregateGateVerdict(gateKey, verdicts)
        overallList = chain.get(GATE_OVERALL) or []
        if overallList and GATE_OVERALL not in gen.verdicts:
            aggregated[GATE_OVERALL] = overallList[0]
        if not aggregated:
            return
        if GATE_SURVIVAL in aggregated and gen.status == GenerationStatus.PROPOSED.value:
            first = {GATE_SURVIVAL: aggregated.pop(GATE_SURVIVAL)}
            self._ledger.recordVerdicts(gen.generationNo, first)
        if aggregated:
            self._ledger.recordVerdicts(gen.generationNo, aggregated)

    # ── G2/G3 业务/回归判据（ShadowVerify 的 businessCriteria 注入面） ──

    def _defaultBusinessCriteria(
        self, change: ShadowChange, probeVerdicts: Dict[str, GateVerdict]
    ) -> Dict[str, GateVerdict]:
        """G2 业务判据 + G3 回归判据：eval_harness 决策档 A/B（R1 测量机复用）。

        baseline = 当前活值快照（父代基线态）；candidate = 代入候选覆盖后的快照。
        - G2 业务：决策档总分「不升不拒、显著回退拒」——确定性 harness 零采样
          噪声，任何实测下降即回退证据；
        - G3 回归：与父代基线例级 A/B 零退化（复用
          ``eval.runner._caseRegressionReadout`` 共享判据机器，不另造第二套）。
        """
        unevidenced = {
            _BUSINESS_VERDICT_KEY: GateVerdict.unevidenced(
                "G2 业务判据无法取证: 缺评测机或活值快照源（不冒充通过）",
                evidence={"gate": _BUSINESS_VERDICT_KEY},
            ),
            _REGRESSION_VERDICT_KEY: GateVerdict.unevidenced(
                "G3 回归判据无法取证: 缺评测机或活值快照源（不冒充通过）",
                evidence={"gate": _REGRESSION_VERDICT_KEY},
            ),
        }
        harness = self._ensureEvalHarness()
        live = self._liveParamsSnapshot()
        if harness is None or live is None:
            return unevidenced
        try:
            baseline = harness.run(live)
            candidate = harness.run(
                _applyOverridesToSnapshot(live, change.parameterOverrides)
            )
        except Exception as exc:  # noqa: BLE001 - 判据执行异常按 failed 点名
            return {
                _BUSINESS_VERDICT_KEY: GateVerdict.failed(
                    f"G2 业务判据执行异常: {exc}", evidence={"gate": _BUSINESS_VERDICT_KEY}
                ),
                _REGRESSION_VERDICT_KEY: GateVerdict.failed(
                    f"G3 回归判据执行异常: {exc}", evidence={"gate": _REGRESSION_VERDICT_KEY}
                ),
            }
        return {
            _BUSINESS_VERDICT_KEY: self._businessVerdict(baseline, candidate),
            _REGRESSION_VERDICT_KEY: self._regressionVerdict(baseline, candidate),
        }

    @staticmethod
    def _businessVerdict(baseline: Any, candidate: Any) -> GateVerdict:
        baseState = baseline.get("state") if isinstance(baseline, dict) else None
        candState = candidate.get("state") if isinstance(candidate, dict) else None
        if baseState != "measured" or candState != "measured":
            return GateVerdict.unevidenced(
                f"G2 业务判据无实测读数（baseline={baseState}, candidate={candState}）",
                evidence={"gate": _BUSINESS_VERDICT_KEY},
            )
        baseScore = float(baseline.get("score") or 0.0)
        candScore = float(candidate.get("score") or 0.0)
        delta = round(candScore - baseScore, 6)
        if delta < 0:
            return GateVerdict.failed(
                f"G2 业务判据失败: 决策档总分回退 {baseScore:.4f} -> {candScore:.4f}（delta={delta}）",
                evidence={
                    "gate": _BUSINESS_VERDICT_KEY,
                    "baseline": baseScore,
                    "candidate": candScore,
                    "delta": delta,
                },
            )
        return GateVerdict.passed(
            f"G2 业务判据通过: 决策档总分不降（{baseScore:.4f} -> {candScore:.4f}）",
            evidence={
                "gate": _BUSINESS_VERDICT_KEY,
                "baseline": baseScore,
                "candidate": candScore,
                "delta": delta,
            },
        )

    @staticmethod
    def _regressionVerdict(baseline: Any, candidate: Any) -> GateVerdict:
        """G3：与父代基线例级 A/B 零退化（共享判据机器，不另造第二套）。"""
        from neurova.evolution.eval.runner import _caseRegressionReadout

        baseById = {
            c.get("id"): c.get("score") for c in ((baseline or {}).get("cases") or [])
        }
        caseScores: Dict[str, Dict[str, Any]] = {}
        for c in ((candidate or {}).get("cases") or []):
            base = baseById.get(c.get("id"))
            score = c.get("score")
            if base is None or score is None:
                continue
            caseScores[str(c["id"])] = {
                "baseline": base,
                "candidate": score,
                "baseline_failed": False,
                "candidate_failed": False,
            }
        regressions, unevidenced = _caseRegressionReadout(caseScores)
        if regressions:
            return GateVerdict.failed(
                f"G3 回归判据失败: 例级退化 {len(regressions)} 例: {regressions[:6]}",
                evidence={"gate": _REGRESSION_VERDICT_KEY, "regressions": regressions},
            )
        if unevidenced:
            return GateVerdict.unevidenced(
                f"G3 回归判据无证据: {len(unevidenced)} 例无法对照",
                evidence={"gate": _REGRESSION_VERDICT_KEY, "unevidenced": unevidenced},
            )
        return GateVerdict.passed(
            f"G3 回归判据通过: 例级 A/B 零退化（{len(caseScores)} 例对照）",
            evidence={"gate": _REGRESSION_VERDICT_KEY, "compared": len(caseScores)},
        )

    def _ensureEvalHarness(self) -> Optional[Any]:
        if self._evalHarness is None:
            try:
                from neurova.evolution.rsi.eval_harness import RSIEvalHarness

                self._evalHarness = RSIEvalHarness()
            except Exception as exc:  # noqa: BLE001 - 评测机缺席如实降级
                logger.warning("eval_harness 装配失败，G2/G3 判据将落 unevidenced: %s", exc)
                return None
        return self._evalHarness

    def _liveParamsSnapshot(self) -> Optional[Dict[str, Dict[str, Any]]]:
        """当下可优化参数活值快照（G2/G3 的基线态；取自 RSI 编排器同一份派生）。"""
        if self._rsi is None:
            return None
        try:
            return self._rsi._current_live_params()
        except Exception as exc:  # noqa: BLE001 - 快照失败如实降级，不编造基线
            logger.warning("活值快照读取失败，G2/G3 判据将落 unevidenced: %s", exc)
            return None

    # ── 影子执行器与隔离根回收 ────────────────────────────────

    def _shadow(self) -> Any:
        if self._shadowVerify is None:
            self._shadowVerify = ShadowVerify(businessCriteria=self._defaultBusinessCriteria)
        return self._shadowVerify

    def _cleanupShadowRoots(self, roundNo: int) -> None:
        """回收影子隔离数据根（结论已入账/入存，只认 neurovaShadow- 前缀防误删）。"""
        for result in self._roundShadow.get(int(roundNo), {}).values():
            dataRoot = str(getattr(result, "dataRoot", "") or "")
            if dataRoot and Path(dataRoot).name.startswith(_SHADOW_ROOT_PREFIX):
                shutil.rmtree(dataRoot, ignore_errors=True)
