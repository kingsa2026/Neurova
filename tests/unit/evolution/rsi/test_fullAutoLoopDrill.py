"""P1-6 全自动闭环贯通演练（总纲验收：进化全程自动进行，跑不通自动回滚）。

设计出处：docs/04-plans/2026-11-21-recursive-self-evolution-plan.md
§2.0 总体纲要、§6 P1 批 P1-6、§7 全局验收判据第 6 条。

总纲口径：对低风险对象，信号立案 → 候选生成 → 影子验证 → 门禁裁决 →
晋升部署 → 运行观测 →（故障时）自动回滚，全链**零人工介入**且全程留痕；
人工只保留三处（裁判件/禁改清单变更、相位未达标的高危 L2 放行、相位初始
信任设定）。本演练的测试装配（auto 档对象登记 + 相位覆盖到 2）即"相位的
初始信任设定"这一保留点的替身，一次性完成——除此之外断言全程无任何人工
审批动作。

三段演练（对应 §7-6）：

1. 演练一（零人工晋升）：auto 档低风险对象（测试专用注册表实例，不污染
   生产单例）+ 相位覆盖 2 + 实做计数达标（R6 门槛，单源
   governance_settings.rsi_phase_min_applied）→ 构造反馈信号 → 候选 →
   影子验证（真子进程 + 隔离数据根 + 真探针六判据）→ GateChain →
   自动晋升（无任何人工调用）→ 金丝雀窗满 promoted → 世代/账本/留痕完整；
2. 演练二（自动回滚）：同链路在第 2 代金丝雀窗内注入 should_rollback 命中
   （负增益）→ 自动回滚到父代：参数实值恢复、markRolledBack 留痕、
   rollback_manager 记账、下一代以恢复后的基线为父，全程零人工；
3. 演练三（失败淘汰）：影子验证 failed 的候选（真子进程注入装配爆炸）→
   世代自动 rejected、参数不落地、生产链路无感（run_iteration 正常返回）。

影子验证一律走真实 ShadowVerify（独立子进程 + NEUROVA_DATA_DIR 隔离数据根
+ SurvivalProbe 六判据 + 架构守卫子集），不用替身——总纲验收的是真实管线
的自动执行能力。信号面按任务书允许以构造反馈驱动（验收的是"管线自动执行"，
不是生产信号自发产生）。
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict

import pytest

from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
from neurova.evolution.closed_loop import AdaptiveToolWeights
from neurova.evolution.experience_feedback import ExperienceFeedback
from neurova.evolution.rsi.gate_verdict import STATE_FAILED, STATE_PASSED
from neurova.evolution.rsi.generation_ledger import GenerationLedger, GenerationStatus
from neurova.evolution.rsi.generation_orchestrator import (
    RSI_PARAMETER_FAMILY_TARGET,
    GenerationOrchestrator,
)
from neurova.evolution.rsi.orchestrator import RSIManualApplyError, RSIOrchestrator
from neurova.evolution.rsi.shadow_verify import ShadowChange, ShadowVerify
from neurova.evolution.rsi.target_registry import (
    EvolutionTarget,
    EvolutionTargetRegistry,
)

ENV_GENERATIONS = "NEUROVA_EVOLUTION_GENERATIONS"

#: 金丝雀观测窗（秒）：短窗让"窗满晋升"在测试时序内确定发生。
CANARY_WINDOW_S = 0.2
#: 窗满等待：略大于窗长，保证检查点时刻 elapsed >= window。
CANARY_SETTLE_S = 0.35


@pytest.fixture(autouse=True)
def _cleanGenerationsEnv(monkeypatch):
    """默认摘掉世代账本 env：任何用例都不许隐式写仓库 data/（状态污染防线）。"""
    monkeypatch.delenv(ENV_GENERATIONS, raising=False)
    yield


def _writePhase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: int) -> None:
    """阶段经治理设置进入（conftest 规则 1：禁止私赋 deployment phase）。"""
    path = tmp_path / "governance_settings.json"
    path.write_text(
        json.dumps({"rsi_phase": phase, "conversation_rules_enabled": False}),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS", str(path))


def _buildSystems() -> dict:
    """四闭环真实子系统：tool_memory 0.85 vs setpoint 0.8 是当前全仓唯一
    真实梯度，保证每轮都有候选（构造反馈信号的生产同构形态）。"""
    weights = AdaptiveToolWeights()
    for _ in range(7):
        weights.update_weight("web_fetch", True)
    for _ in range(3):
        weights.update_weight("web_fetch", False)
    return {
        "sleep": SleepConsolidation(),
        "emotion": EmotionModule(),
        "experience": ExperienceFeedback(),
        "tool_memory": ToolMemoryIntegration(
            memory_layer=None,
            muscle_memory=None,
            tool_weights=weights,
            confidence_threshold=0.8,
            temperature_threshold=30.0,
            muscle_memory_threshold=0.85,
        ),
    }


def _buildOrchestrator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: int
) -> RSIOrchestrator:
    _writePhase(tmp_path, monkeypatch, phase)
    systems = _buildSystems()
    return RSIOrchestrator(
        sleep_system=systems["sleep"],
        emotion_system=systems["emotion"],
        experience_system=systems["experience"],
        tool_memory_system=systems["tool_memory"],
        agent_id="full-auto-drill",
    )


class _AutoTierTestRegistry(EvolutionTargetRegistry):
    """测试专用注册表实例（不触碰生产单例 get_target_registry）：

    仅登记一个 auto 档低风险 L1 对象（rsi.parameterFamily，§8-1 拍板：
    低风险对象 G0-G3 全绿即自动晋升金丝雀）。自动化的主体是循环，
    严格发生在注册表登记的对象与判据之内（§2.0）。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._targets: Dict[str, EvolutionTarget] = {}
        self.register(
            EvolutionTarget(
                targetId=RSI_PARAMETER_FAMILY_TARGET,
                layer="L1",
                kind="policyParam",
                locator=(
                    "neurova/evolution/rsi/integration_manager.py:"
                    "RSIIntegrationManager.OPTIMIZABLE_PARAMETERS"
                ),
                scope="global",
                gateLevel="auto",
                survivalCritical=False,
                fallbackRef="neurova/evolution/evolution_settings.py:_defaults",
                verdictSuite="rsi.eval.decision",
            )
        )


def _attach(
    orch: RSIOrchestrator,
    *,
    canaryWindowSeconds: float = CANARY_WINDOW_S,
    shadowVerify: Any = None,
) -> GenerationOrchestrator:
    """挂接世代编排器：shadowVerify=None → 真 ShadowVerify（真子进程影子验证）。"""
    genOrch = GenerationOrchestrator(
        rsiOrchestrator=orch,
        ledger=GenerationLedger(),
        registry=_AutoTierTestRegistry(),
        shadowVerify=shadowVerify,
        canaryWindowSeconds=canaryWindowSeconds,
    )
    orch.generationOrchestrator = genOrch
    return genOrch


def _toolMemoryThreshold(orch: RSIOrchestrator) -> float:
    params = {
        p.name: p.current_value
        for p in orch.integration_manager.get_optimizable_parameters()["tool_memory"]
    }
    return params["muscle_memory_threshold"]


def _assertCompleteDeployedGeneration(gen, *, parentNo) -> None:
    """世代/账本/留痕完整性判据：门禁、裁决、部署、谱系、信号、变更全链有档。"""
    assert gen is not None
    assert gen.status == GenerationStatus.DEPLOYED.value
    assert gen.parentNo == parentNo
    # 基线 commit 冻结：开代时刻定格的短 hash。共享工作树上 HEAD 会被并行
    # 会话推进，故断言其形态（非 unknown 的短 hash）而非与当下 HEAD 相等
    #（P1-3 同款判据）；账本落盘不回改，冻结性由同一值跨读取不变保证。
    assert gen.basisCommit != "unknown" and gen.basisCommit != ""
    assert re.fullmatch(r"[0-9a-f]{7,40}", gen.basisCommit), "基线 commit 必须冻结可复现"
    # 门禁链全绿（G0-G3 + overall，L1 无 G4 键）
    for gate in ("g0", "g1", "g2", "g3", "overall"):
        assert gate in gen.verdicts, f"门禁结论缺 {gate}"
        assert gen.verdicts[gate].state == STATE_PASSED
    # 裁决 = auto、无审批人（零人工的直接证据）
    assert gen.decision is not None and gen.decision.kind == "auto"
    assert gen.decision.approver == ""
    # 部署留痕：晋升时刻 + 金丝雀观测窗起点
    assert gen.deployment is not None and gen.deployment.promotedAt
    assert gen.deployment.canaryStartedAt, "观测窗起点必须随代留痕"
    # 信号（为什么改）与变更（改了什么）可追溯
    kinds = {s.kind for s in gen.signals}
    assert "feedback" in kinds and "convergence" in kinds
    assert gen.changes, "候选必须映射为变更引用"
    assert all(c.targetId == RSI_PARAMETER_FAMILY_TARGET for c in gen.changes)
    assert any("muscle_memory_threshold" in c.ref for c in gen.changes)


# ══════════════════════════════════════════════════════════════════
# 演练一：零人工晋升——信号 → 候选 → 影子验证（真子进程）→ 门禁 →
# 自动晋升 → 金丝雀窗满 promoted，全程无任何人工调用
# ══════════════════════════════════════════════════════════════════


class TestZeroHumanPromotionDrill:
    @pytest.mark.timeout(1800)
    def test_signalToPromotionWithoutAnyHumanAction(self, tmp_path, monkeypatch):
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=2)
        genOrch = _attach(orch)

        # 三轮全自动迭代（R6 实做计数门槛：phase 2 晋升需 ≥3 次真实应用）
        for roundNo in (1, 2, 3):
            result = orch.run_iteration()
            assert result["optimizations"], f"r{roundNo}：构造反馈信号必须产出候选"
            assert (
                result["applied_count"] >= 1
            ), f"r{roundNo}：phase 2 自动档必须自动应用（零人工）"
            # 金丝雀观测窗满 → 晋升（生产观测入口 observeOpenCanaries，非人工）
            time.sleep(CANARY_SETTLE_S)
            genOrch.observeOpenCanaries({})
            _assertCompleteDeployedGeneration(
                genOrch.generationForRound(roundNo),
                parentNo=None if roundNo == 1 else roundNo - 1,
            )

        ledger = genOrch.generationLedger()
        # 谱系链完整：1 ← 2 ← 3，基线指认第 3 代
        assert ledger.currentBaseline().generationNo == 3
        lineage = [g.generationNo for g in ledger.lineage(3)]
        assert lineage == [3, 2, 1]

        # 实做计数达标：对照 R6 门槛单源（governance_settings.rsi_phase_min_applied）
        from neurova.security.governance_settings import resolveRsiPhaseMinApplied

        required = resolveRsiPhaseMinApplied().get(2)
        assert required is not None and required >= 1
        assert orch._phase_applied_counts.get(2, 0) >= required, (
            f"实做计数达标（R6：phase 2 需 ≥{required} 次真实应用），实际 "
            f"{orch._phase_applied_counts.get(2, 0)}"
        )

        # 全程零人工审批动作：无待批提案、无审批人署名、人工通道无可批对象
        status = orch.get_status()
        assert status["pending_manual_optimizations"] == 0
        assert status["last_round_proposals"]["state"] == "applied_auto"
        assert status["last_round_proposals"]["applied_by"] is None
        with pytest.raises(RSIManualApplyError) as err:
            orch.applyApprovedOptimizations(approved_by="should-not-be-needed")
        assert err.value.status_code == 409, "全程未走人工通道，提案已被自动档消费"

        # 无回滚发生（健康晋升），无遗留开窗
        assert orch.rollback_manager.get_rollback_history() == []
        assert genOrch.canaryReadout()["count"] == 0
        assert genOrch.lastPipelineError is None, "管线零故障：演练全程无异常留痕"


# ══════════════════════════════════════════════════════════════════
# 演练二：自动回滚——同链路第 2 代窗内 should_rollback 命中（负增益）
# → 自动回滚到父代，参数实值恢复、留痕、下一代以恢复后基线为父
# ══════════════════════════════════════════════════════════════════


class TestAutoRollbackDrill:
    @pytest.mark.timeout(1800)
    def test_canaryBreachAutoRollsBackToParentWithoutHuman(self, tmp_path, monkeypatch):
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=2)
        genOrch = _attach(orch, canaryWindowSeconds=0.3)

        # 第 1 代：同一条全自动链路晋升为父代基线
        orch.run_iteration()
        time.sleep(CANARY_SETTLE_S)
        genOrch.observeOpenCanaries({})
        parent = genOrch.generationLedger().currentBaseline()
        assert parent is not None and parent.generationNo == 1
        parentNo = parent.generationNo
        parentParam = _toolMemoryThreshold(orch)

        # 第 2 代：同链路自动开代、自动应用、进入金丝雀观测窗
        orch.run_iteration()
        gen2 = genOrch.generationForRound(2)
        assert gen2.status == GenerationStatus.CANARY.value, "窗未满应处于观测态"
        assert gen2.parentNo == parentNo
        canaryParam = _toolMemoryThreshold(orch)
        assert canaryParam != parentParam, "前提：观测窗内参数已应用（受限发布）"

        # 窗内注入 should_rollback 命中读数（负增益）→ 全自动回滚，无人工确认
        historyBefore = len(orch.rollback_manager.get_rollback_history())
        settled = genOrch.canaryCheckpoint(2, readings={"gain": -0.5})

        assert settled.status == GenerationStatus.ROLLED_BACK.value
        assert settled.deployment.rolledBackTo == parentNo, "回滚落点 = 父代"
        assert "gain" in (settled.deployment.canaryConclusion or ""), "回滚原因必须留痕"
        assert settled.deployment.canaryStartedAt, "观测窗起点随代留痕"
        # 参数实值恢复到父代（复用 R1 应用前快照恢复路径）
        assert _toolMemoryThreshold(orch) == parentParam
        # rollback_manager 留痕（晋升判据"距上次回滚天数"的唯一数据源）
        assert len(orch.rollback_manager.get_rollback_history()) == historyBefore + 1
        # 回滚后该世代终止：生产基线指认回父代
        assert genOrch.generationLedger().currentBaseline().generationNo == parentNo
        assert genOrch.canaryReadout()["count"] == 0, "回滚后开窗应关闭"

        # 下一代以恢复后的基线为父（全自动继续演化，不等待人工救援）
        orch.run_iteration()
        gen3 = genOrch.generationForRound(3)
        assert gen3 is not None
        assert gen3.parentNo == parentNo, "回滚后新一代的父代 = 恢复后的基线"
        time.sleep(CANARY_SETTLE_S)
        genOrch.observeOpenCanaries({})
        assert gen3.status == GenerationStatus.DEPLOYED.value, "回滚后演化继续自动推进"


# ══════════════════════════════════════════════════════════════════
# 演练三：失败淘汰——影子验证 failed 的候选 → 世代自动 rejected、
# 参数不落地、生产链路无感
# ══════════════════════════════════════════════════════════════════


class _PoisonedRealShadow:
    """真实 ShadowVerify 的薄包装：给候选挂测试注入执行器引用，验证全程
    走真子进程 + 真探针（P1-2 离线注桩通道，不真改仓库文件）。"""


class TestShadowFailureEliminationDrill:
    @pytest.mark.timeout(1800)
    def test_failedShadowCandidateAutoRejectedAndNeverLands(self, tmp_path, monkeypatch):
        helperDir = tmp_path / "drillExecutors"
        helperDir.mkdir(parents=True)
        (helperDir / "drillPoisonExecutor.py").write_text(
            "def apply(change):\n"
            "    import neurova.api.app as appModule\n"
            "    def boom(*args, **kwargs):\n"
            "        raise RuntimeError('演练注入：装配爆炸')\n"
            "    appModule.create_app = boom\n",
            encoding="utf-8",
        )

        class _PoisonedShadow:
            def __init__(self, inner: ShadowVerify, executorRef: str):
                self._inner = inner
                self._executorRef = executorRef

            def verify(self, change):
                poisoned = ShadowChange(
                    changeId=change.changeId,
                    kind="identity",
                    targetId=change.targetId,
                    executorRef=self._executorRef,
                )
                return self._inner.verify(poisoned)

        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=2)
        poisonedShadow = _PoisonedShadow(
            ShadowVerify(extraSysPath=[str(helperDir)]), "drillPoisonExecutor:apply"
        )
        genOrch = _attach(orch, shadowVerify=poisonedShadow)

        paramBefore = _toolMemoryThreshold(orch)
        # 生产链路无感：run_iteration 正常返回，不因影子失败抛错
        result = orch.run_iteration()
        assert result["optimizations"], "候选照常产出（信号→候选环节不受影子结论影响）"

        gen = genOrch.generationForRound(1)
        assert gen is not None
        # 世代自动 rejected（G0 存活门一票否决 + 短路）
        assert gen.status == GenerationStatus.REJECTED.value
        assert gen.verdicts["g0"].state == STATE_FAILED
        assert gen.verdicts["overall"].state == STATE_FAILED
        assert "g1" not in gen.verdicts and "g2" not in gen.verdicts, (
            "G0 短路：后续门禁不参评"
        )
        assert gen.decision is not None and gen.decision.kind == "rejected"
        assert gen.decision.reason, "拒绝必须留痕原因（可归因）"

        # 参数不落地：门禁拒绝的世代，自动档不得应用（总纲：生产基线只接受
        # 全绿世代；影子失败 → 候选自动淘汰）
        assert result["applied_count"] == 0
        assert _toolMemoryThreshold(orch) == paramBefore, "影子失败的候选参数不得落地"
        assert orch.rollback_manager.get_rollback_history() == []

        # 无基线产生、人工通道同样被拒（双通道都不给坏候选落地）
        assert genOrch.generationLedger().currentBaseline() is None
        with pytest.raises(RSIManualApplyError) as err:
            orch.applyApprovedOptimizations(approved_by="anyone")
        assert err.value.status_code == 409
        assert _toolMemoryThreshold(orch) == paramBefore
