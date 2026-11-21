"""R6 · 晋升实做次数门槛（红→绿 TDD，拍板 2026-11-21，详案 §6-R6 / §8-10）。

根因：`rsi_phase=4` 顶格与"1018 轮迭代 0 次应用"的证据脱节——晋升判据只看
收敛/ROI/回滚天数/经验质量，没有一条问"这个相位真的应用过几次优化"，
于是空转也能一路升到全自动档。本文件把"真的做过"钉成硬门槛：

- 晋升 2→3 需当前相位（phase 2）下 ≥3 次真实应用；晋升 3→4 需 ≥10 次；
  真实应用 = `applied_count>0` 的迭代计数（phase 1→2 无此要求）；
- 有读数且不足 ⇒ `failed`，reason 点名"实做次数不足：当前相位 X 累计
  applied=N，晋升要求 ≥M"；
- 读数缺失（无法计数）⇒ `unevidenced`，不得当 0 糊弄（三态契约同款）；
- 门槛表单源 `governance_settings.rsi_phase_min_applied`（默认 {"2":3,"3":10}），
  决策时刻读取——改事实源判据跟着翻，不做构造期快照。

编排器侧的供值契约：`run_iteration` 在应用段按"当前 deployment_phase"累计
逐相位计数，并在阶段评估时以 `phase_applied_count` 喂给判据（0 也要喂，
缺席才是"无法计数"）。
"""

from __future__ import annotations

import json

import pytest

from neurova.evolution.rsi.deployment_controller import RSIDeploymentController
from neurova.evolution.rsi.gate_verdict import GateVerdict
from neurova.evolution.rsi.metrics import RSIMetrics
from neurova.security.governance_settings import DEFAULTS, resolveRsiPhaseMinApplied


def _good_experience_quality() -> dict:
    """一份"质量有证据且为正面"的读数（经 RSIMetrics 供值口，不手写形态）。"""
    metrics = RSIMetrics()
    metrics.record_metric(RSIMetrics.EXPERIENCE_ROWS, 9)
    metrics.record_metric(RSIMetrics.EXPERIENCE_ADOPTION_DECISIONS, 5)
    metrics.record_metric(RSIMetrics.EXPERIENCE_ADOPTION_SUCCESS_RATE, 0.9)
    return metrics.experience_quality_readout()


def _satisfied_metrics(phase: int, applied: int | None = None) -> dict:
    """除实做次数外全部满足的晋升读数；`applied=None` 表示整键缺席（无法计数）。"""
    metrics = {
        "convergence_status": "converging",
        "roi": 0.2,
        "days_without_rollback": 40,
        "experience_quality": _good_experience_quality(),
    }
    if applied is not None:
        metrics["phase_applied_count"] = applied
    return metrics


# ── 1. 判据本体：门槛、点名、三态 ─────────────────────────────────


def test_zeroAppliedAtPhaseTwoFailsTheGate():
    """红灯靶：phase 2 累计 applied=0 时晋升必须被否决并点名"实做次数"。

    改判据前该场景（其余读数全部满足）会放行——空转升顶的结构性漏洞。
    """
    verdict = RSIDeploymentController(initial_phase=2).evaluate_phase_transition(
        _satisfied_metrics(2, applied=0))

    assert verdict.state == "failed", verdict.reason
    assert "实做次数" in verdict.reason, verdict.reason
    assert "applied=0" in verdict.reason, verdict.reason


def test_belowThresholdNamesPhaseCountAndRequirement():
    """不足时 reason 要能对账：当前相位、累计数、要求值三个数都在。"""
    verdict = RSIDeploymentController(initial_phase=2).evaluate_phase_transition(
        _satisfied_metrics(2, applied=2))

    assert verdict.state == "failed"
    assert "当前相位 2" in verdict.reason, verdict.reason
    assert "applied=2" in verdict.reason, verdict.reason
    assert "≥3" in verdict.reason, verdict.reason


def test_thresholdMetDoesNotBlock():
    """门槛满足（phase 2 累计 applied=3）且其余判据满足 ⇒ 放行。"""
    verdict = RSIDeploymentController(initial_phase=2).evaluate_phase_transition(
        _satisfied_metrics(2, applied=3))

    assert verdict.state == "passed", verdict.reason


def test_phaseOneHasNoAppliedRequirement():
    """1→2 无实做次数要求：手动档还没自动执行过，卡次数会把晋升链锁死。"""
    metrics = _satisfied_metrics(1, applied=0)
    metrics["days_without_rollback"] = 8  # 1→2 真正的门槛是 7 天无回滚

    verdict = RSIDeploymentController(initial_phase=1).evaluate_phase_transition(metrics)

    assert verdict.state == "passed", verdict.reason


def test_phaseThreeToFourNeedsTenApplications():
    """3→4 的门槛是 10 次：9 次否决、10 次放行（含边界，拍板口径 ≥10）。"""
    controller = RSIDeploymentController(initial_phase=3)

    short = controller.evaluate_phase_transition(_satisfied_metrics(3, applied=9))
    assert short.state == "failed", short.reason
    assert "applied=9" in short.reason and "≥10" in short.reason, short.reason

    met = controller.evaluate_phase_transition(_satisfied_metrics(3, applied=10))
    assert met.state == "passed", met.reason


def test_missingReadingIsUnevidencedNotZero():
    """读数缺席 = 无法计数 ⇒ unevidenced，不得当 0 糊弄、也不得放行。"""
    verdict = RSIDeploymentController(initial_phase=2).evaluate_phase_transition(
        _satisfied_metrics(2, applied=None))

    assert verdict.state == "unevidenced", verdict.reason
    assert "phase_applied_count" in verdict.reason, verdict.reason


def test_nonNumericReadingIsUnevidenced():
    """喂进来的读数不是数（如残缺对象）同样按"无法计数"处理。"""
    verdict = RSIDeploymentController(initial_phase=2).evaluate_phase_transition(
        _satisfied_metrics(2, applied=None) | {"phase_applied_count": "三"})

    assert verdict.state == "unevidenced", verdict.reason


# ── 2. 门槛表单源：默认值 + 活旋钮 ────────────────────────────────


def test_defaultsPinTheAdjudicatedThresholds():
    """默认门槛表 = 拍板值 {2:3, 3:10}，键是"当前相位"而非目标相位。"""
    assert DEFAULTS["rsi_phase_min_applied"] == {"2": 3, "3": 10}
    assert resolveRsiPhaseMinApplied({}) == {2: 3, 3: 10}


def test_thresholdKnobIsLiveAtDecisionTime(tmp_path, monkeypatch):
    """同一份读数，改事实源的门槛 ⇒ 结论当场翻转（构造期快照式实现必红）。"""
    controller = RSIDeploymentController(initial_phase=2)
    metrics = _satisfied_metrics(2, applied=3)
    assert controller.evaluate_phase_transition(metrics).state == "passed"

    settings = tmp_path / "governance_settings.json"
    settings.write_text(
        json.dumps({"rsi_phase_min_applied": {"2": 5}}), encoding="utf-8")
    monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS", str(settings))

    verdict = controller.evaluate_phase_transition(metrics)
    assert verdict.state == "failed", f"门槛是幻影旋钮：改事实源没动判据（{verdict}）"
    assert "≥5" in verdict.reason, verdict.reason


def test_malformedThresholdEntriesAreDroppedNotFudged():
    """门槛表里的垃圾条目丢弃，不得读成 0/1 之类的放行值。"""
    thresholds = resolveRsiPhaseMinApplied(
        {"rsi_phase_min_applied": {"2": "很多", "3": None, "9": 5, "1": 2}})

    assert thresholds == {1: 2}, thresholds


# ── 3. 编排器供值：按当前相位累计、0 也如实喂 ──────────────────────


def _spy_gate(orchestrator, captured: list):
    def _spy(metrics):
        captured.append(dict(metrics))
        return GateVerdict.failed("spy：只捕获供值，不放行")

    orchestrator.deployment_controller.evaluate_phase_transition = _spy


def test_orchestratorAccumulatesPerPhaseAppliedCount(rsi_probe_factory):
    """phase 2 下每轮真实应用 1 次 ⇒ 判据读到的累计数逐轮 +1。"""
    probe = rsi_probe_factory(rsi_phase=2)
    captured: list = []
    _spy_gate(probe.orchestrator, captured)

    probe.run(3)

    assert probe.applied_total == 3, "前置：探针回路应真的应用过"
    assert [m.get("phase_applied_count") for m in captured] == [1, 2, 3], captured


def test_orchestratorFeedsZeroWhenNothingApplied(rsi_probe_factory, monkeypatch):
    """没应用过也要喂 0（可计数的事实），缺席只留给"无法计数"的场景。"""
    probe = rsi_probe_factory(rsi_phase=2)
    monkeypatch.setattr(probe.orchestrator, "generate_optimizations",
                        lambda *a, **kw: [])
    captured: list = []
    _spy_gate(probe.orchestrator, captured)

    probe.run(1)

    assert captured, "判据未被调用"
    assert captured[0].get("phase_applied_count") == 0, captured[0]
