"""RSI 系统性能估算器

为 RSI 棘轮提供"真实梯度"：每个闭环系统的可优化参数都有各自的
setpoint（设计最优点），性能分 = 基础反馈信号 + 参数贴近度各占一半。

此前 RSI 失控漂移的本质：sleep/emotion 的 get_feedback() 不暴露任何
性能键，参数怎么调都测不到差别——没有梯度就没有改进方向。
"""

from typing import Any, Dict

# 各系统可优化参数的设计最优点（setpoint）
SYSTEM_SETPOINTS: Dict[str, Dict[str, float]] = {
    "sleep": {
        "base_decay_rate": 0.1,
        "similarity_threshold": 0.8,
        "merge_threshold": 0.9,
    },
    "emotion": {
        "emotional_protection_threshold": 0.5,
        "emotional_protection_factor": 1.0,
    },
    "experience": {
        "crystallize_min_observations": 3,
        "crystallize_min_success_rate": 0.6,
        "pattern_min_support": 2,
    },
    "tool_memory": {
        "success_bonus": 0.1,
        "failure_penalty": 0.5,
        "decay_rate": 0.1,
        "muscle_memory_threshold": 0.8,
    },
}


def get_setpoint(system_name: str, param_name: str):
    """查询参数 setpoint；未知返回 None"""
    return SYSTEM_SETPOINTS.get(system_name, {}).get(param_name)


def estimate_system_performance(
    system_name: str, feedback: Dict[str, Any], params: Dict[str, Any]
) -> float:
    """估算单个闭环系统的性能分（0..1）。

    组成：
    - 基础反馈信号（30%）：feedback 中显式的 performance_score，退化为
      success_rate；都没有则取中性 0.5。
    - 参数贴近度（70%）：可优化参数相对 setpoint 的归一化平均距离，
      越近越高——这为棘轮提供真实的改进方向与幅度。权重更高是因为
      基础反馈常与其他参数耦合（如 success_rate 受多参数影响），
      参数梯度才是唯一可控、可信的改进信号。

    无任何已知参数时退化为纯基础分（观察模式仍有意义）。
    """
    # ---- 基础反馈信号 ----
    base_raw = feedback.get("performance_score")
    if not isinstance(base_raw, (int, float)):
        base_raw = feedback.get("success_rate")
    if not isinstance(base_raw, (int, float)):
        base_raw = 0.5
    base = max(0.0, min(1.0, float(base_raw)))

    # ---- 参数贴近度 ----
    setpoints = SYSTEM_SETPOINTS.get(system_name, {})
    if not setpoints or not params:
        return base

    distances = []
    for param_name, sp in setpoints.items():
        val = params.get(param_name)
        if val is None or not isinstance(val, (int, float)):
            continue
        try:
            val_f, sp_f = float(val), float(sp)
        except (TypeError, ValueError):
            continue
        tol = max(abs(sp_f), 1e-6)
        distance = min(1.0, abs(val_f - sp_f) / tol)
        distances.append(distance)

    if not distances:
        return base

    param_score = 1.0 - (sum(distances) / len(distances))
    score = 0.3 * base + 0.7 * param_score
    return max(0.0, min(1.0, score))
