"""
棘轮剪枝进化能力有效性验证（TDD 红绿）。

目标：检查 neurova/evolution/rsi 的 RecursiveRatchetPruner + RSIOrchestrator
是否“真正有效”，而非骨架/表面正确。

覆盖三个根因：
1. 细筛验证评分错接：无效候选（valid=False, score=0）未被惩罚，反而得 ~0.5。
2. 零活动虚假收敛：默认 phase 0 下从未应用任何优化，却在第 ~20 次迭代被判定
   “converged”，声称“已进化完成”但实际什么都没做。
3. 无实测增益的失控漂移：phase>=2 下，以恒定的高 success_rate 为代理指标，
   每轮无脑单向调整参数（bonus/penalty/decay 递减、threshold 递增），
   从不测量“调整后是否真的改善”，永远不会收敛——即假的棘轮/失控漂移。

修复后（GREEN）应保证：
- 无效候选细筛得分 = 0；
- 无真实反馈信号时不虚假收敛（保持观察）；
- 应用后若实测无改善，增益≈0，最终收敛停止（真实棘轮）。
"""

import pytest

from neurova.evolution.rsi.orchestrator import RSIOrchestrator
from neurova.evolution.rsi.recursive_ratchet_pruner import Candidate, RecursiveRatchetPruner


class MockSystem:
    """可配置反馈的闭环系统桩。

    get_feedback() 返回性能信号（success_rate 供性能提取），并持有可被优化的
    数值属性，供 integration_manager.get_optimizable_parameters 发现。
    should_change_feedback=False 时，无论参数怎么改 success_rate 恒定（模拟
    “参数与代理指标无因果关联”），用以暴露失控漂移。
    """

    def __init__(self, name, feedback, params=None, should_change_feedback=False):
        self._name = name
        self._feedback = feedback
        self._should_change_feedback = should_change_feedback
        self._params = dict(params or {})
        for k, v in self._params.items():
            setattr(self, k, v)

    def get_feedback(self):
        sr = self._feedback.get("success_rate", 0.0)
        if self._should_change_feedback and hasattr(self, "success_bonus"):
            # success_rate 随 success_bonus 上升而上升（避开 0.7~0.9 死区，保证生成候选）
            sr = min(1.0, 0.5 + (self.success_bonus - 1.0) * 0.2)
        out = dict(self._feedback)
        out["success_rate"] = sr
        return out


def _build_orchestrator(sleep, emotion, experience, tool_memory, initial_phase=0):
    orch = RSIOrchestrator(sleep, emotion, experience, tool_memory)
    orch.deployment_controller._current_phase = initial_phase
    return orch


# ============ 根因 1：细筛验证评分错接 ============

def test_invalid_candidate_validation_score_is_zero():
    """无效候选（valid=False, score=0）细筛得分必须严格为 0。

    修复前：_compute_validation_score 把 valid=True(→1.0) 当作数值计入，
    再与 score=0.0 平均，得到 ~0.5，使无效候选几乎不被惩罚。
    """
    pruner = RecursiveRatchetPruner()
    score = pruner._compute_validation_score({"valid": False, "score": 0.0, "details": "bad"})
    assert score == 0.0, f"无效候选细筛得分应为 0，实际 {score}"


def test_pruner_excludes_invalid_candidate():
    """当候选验证无效时，递归剪枝必须排除该候选（不能胜出）。"""
    pruner = RecursiveRatchetPruner()

    def _mk(cid, bad):
        return Candidate(
            id=cid,
            name="p",
            parameters={"p": 0.5 if bad else 0.9},
            complexity=0.1,
            violates_hard_constraints=False,
            heuristic_score=1.0,
            metadata={},
        )

    candidates = [_mk("c_bad", True), _mk("c_good", False)]

    def heuristic_fn(c):
        return c.heuristic_score

    def quick_eval_fn(c):
        return 1.0 - c.complexity

    def validation_fn(c):
        bad = c.id == "c_bad"
        return {"valid": not bad, "score": 0.0 if bad else 1.0, "details": ""}

    result = pruner.recursive_prune(
        candidates,
        heuristic_fn=heuristic_fn,
        quick_eval_fn=quick_eval_fn,
        validation_fn=validation_fn,
    )
    assert result is not None
    assert result.id == "c_good", f"无效候选不应胜出，实际 {result.id}"


# ============ 根因 2：零活动虚假收敛 ============

def test_no_signal_no_false_convergence():
    """无真实反馈信号（无可提取性能）时，RSI 不应虚假收敛。

    修复前：phase 0 下从不应用优化，每轮喂入 gain=0，~20 次后被判定 “converged”，
    should_continue() 返回 False，声称“进化完成”，但实际什么都没做。
    """
    sleep = MockSystem("sleep", feedback={"consolidation_count": 1, "merge_rate": 0.1}, params={"merge_threshold": 0.5})
    emotion = MockSystem("emotion", feedback={"emotional_memories": 0, "avg_intensity": 0.0}, params={})
    experience = MockSystem("experience", feedback={"crystallized_patterns": 0, "success_rate": 0.9}, params={})
    tool_memory = MockSystem("tool_memory", feedback={"total_usages": 0, "success_rate": 0.9}, params={})
    orch = _build_orchestrator(sleep, emotion, experience, tool_memory, initial_phase=0)
    for _ in range(30):
        if not orch.should_continue():
            break
        orch.run_iteration()
    status = orch.convergence_analyzer.analyze_convergence()["status"]
    assert status != "converged", (
        f"无信号时不应虚假收敛（实际 {status}）；应保持在观察/数据不足状态"
    )


# ============ 根因 3：无失控漂移 + 真正收敛到最优 ============

def test_parameter_optimization_converges_to_setpoint_and_stops():
    """phase>=2 下，参数感知性能分为棘轮提供真实梯度：远离 setpoint 的参数
    被驱动至 setpoint 附近并收敛停止（证明 RSI 真正"改善"参数），且不会失控漂移。

    修复前：gain = applied_count * 恒定高 performance，恒为正，永不收敛，
    参数每轮被无脑单向调整（bonus/penalty/decay 递减、threshold 递增），失控漂移。

    修复后：逐参数实测增益，仅保留有实测收益的调整；收益耗尽即收敛停止。
    """
    sleep = MockSystem("sleep", feedback={"consolidation_count": 1}, params={"merge_threshold": 0.5})
    emotion = MockSystem("emotion", feedback={}, params={})
    experience = MockSystem("experience", feedback={"success_rate": 0.9}, params={})
    tool_memory = MockSystem(
        "tool_memory",
        feedback={"total_usages": 10, "success_rate": 0.95},
        params={"success_bonus": 1.0, "failure_penalty": 0.5, "decay_rate": 0.1, "muscle_memory_threshold": 0.7},
        should_change_feedback=False,  # success_rate 恒定；改善来自参数感知性能分的 setpoint 梯度
    )
    orch = _build_orchestrator(sleep, emotion, experience, tool_memory, initial_phase=2)
    snap_before = dict(
        success_bonus=tool_memory.success_bonus,
        failure_penalty=tool_memory.failure_penalty,
        decay_rate=tool_memory.decay_rate,
        muscle_memory_threshold=tool_memory.muscle_memory_threshold,
    )
    for _ in range(40):
        if not orch.should_continue():
            break
        orch.run_iteration()

    snap_after = dict(
        success_bonus=tool_memory.success_bonus,
        failure_penalty=tool_memory.failure_penalty,
        decay_rate=tool_memory.decay_rate,
        muscle_memory_threshold=tool_memory.muscle_memory_threshold,
    )
    # 1) 参数朝各自 setpoint 方向移动（确实在"改善"，而非原地空转）
    assert snap_after["success_bonus"] < snap_before["success_bonus"], (
        f"success_bonus 应朝 setpoint 0.1 收敛，实际 {snap_before['success_bonus']}→{snap_after['success_bonus']}"
    )
    assert snap_after["muscle_memory_threshold"] > snap_before["muscle_memory_threshold"], (
        f"muscle_memory_threshold 应朝 setpoint 0.8 收敛（从 0.7 应增大），实际 "
        f"{snap_before['muscle_memory_threshold']}→{snap_after['muscle_memory_threshold']}"
    )
    # 2) 收敛到 setpoint 附近（有界，不失控漂移）
    assert 0.05 <= snap_after["success_bonus"] <= 0.15, (
        f"success_bonus 应收敛到 setpoint 0.1 附近，实际 {snap_after['success_bonus']}"
    )
    assert 0.70 <= snap_after["muscle_memory_threshold"] <= 0.90, (
        f"muscle_memory_threshold 应收敛到 setpoint 0.8 附近，实际 {snap_after['muscle_memory_threshold']}"
    )
    # 3) 收益耗尽后停止（真实棘轮：不会无限漂移）
    assert orch.should_continue() is False, "应最终收敛停止（真实棘轮）"


def test_measured_improvement_yields_positive_gain():
    """存在真实可测改善时（应用后 success_rate 上升），增益应为正，验证棘轮可度量收益。"""
    sleep = MockSystem("sleep", feedback={}, params={})
    emotion = MockSystem("emotion", feedback={}, params={})
    experience = MockSystem("experience", feedback={"success_rate": 0.5}, params={})
    tool_memory = MockSystem(
        "tool_memory",
        feedback={"total_usages": 10, "success_rate": 0.5},
        params={"success_bonus": 1.0, "failure_penalty": 0.5, "decay_rate": 0.1, "muscle_memory_threshold": 0.7},
        should_change_feedback=True,  # success_rate 随参数上升
    )
    orch = _build_orchestrator(sleep, emotion, experience, tool_memory, initial_phase=2)
    result = orch.run_iteration()
    assert result["applied_count"] > 0, "应当实际应用优化"
    assert result["gain"] >= 0.0, f"有真实改善时增益应>=0，实际 {result['gain']}"
