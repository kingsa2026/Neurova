"""RSI 系统性能估算器

为 RSI 棘轮提供"真实梯度"：每个闭环系统的可优化参数都有各自的
setpoint（设计最优点），性能分 = 基础反馈信号 + 参数贴近度各占一半。

此前 RSI 失控漂移的本质：sleep/emotion 的 get_feedback() 不暴露任何
性能键，参数怎么调都测不到差别——没有梯度就没有改进方向。
"""

from typing import Any, Dict, List

# 各系统可优化参数的设计最优点（setpoint）
# 对齐治理（2026-09-12）：原表从 Agent 镜像属性抄写，与真实消费方的设计
# 默认冲突——已全表对齐（依据：融合文档 §7 钉死 tool_memory 三参数；
# EmotionModule/SleepConsolidation/ExperienceFeedback/PatternMiner 类默认）。
# merge_threshold 移除：similarity_threshold 的别名幻影（同一真实参数）。
SYSTEM_SETPOINTS: Dict[str, Dict[str, float]] = {
    "sleep": {
        "base_decay_rate": 0.1,
        "similarity_threshold": 0.7,
    },
    "emotion": {
        "emotional_protection_threshold": 0.5,
        "emotional_protection_factor": 0.3,
    },
    "experience": {
        "crystallize_min_observations": 3,
        "crystallize_min_success_rate": 0.6,
        "pattern_min_support": 2,
    },
    "tool_memory": {
        "success_bonus": 0.1,
        "failure_penalty": 0.05,
        "decay_rate": 0.01,
        "muscle_memory_threshold": 0.8,
    },
    # 上下文经济性族（Issue #289 · 004 M2）。目标值取 `TokenBudget` 的默认构造，
    # 即现网实际值 —— 起点即目标时该族零梯度，棘轮不为"把预算改来改去"而动作。
    "context": {
        "max_total": 16000,
        "memories": 4000,
        "conversation_history": 6000,
        "experience_knowledge": 1500,
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
    # F4（拍板：明示降权路线的分解半）逐项分解快照：代理分不再是黑箱
    # 标量——base/param 两构成与权重随值出街（estimate 无处挂分解体，
    # 由 setpointDecomposition 供读取口径，单一算式两处共用）。
    return max(0.0, min(1.0, score))


def setpointDecomposition(system_name: str, feedback: Dict[str, Any],
                          params: Dict[str, Any]) -> Dict[str, Any]:
    """F4 逐项分解：performance_score 的 base/param 两构成与权重明示。

    明示降权路线的可观测半：0.3/0.7 权重、两构成分、逐参数距离——
    "代理分由什么组成"从此可审计。校准记录字段（calibration）为
    F4 提案 gate 的登记位（无校准记录 = 出厂默认档，如实标注）。
    """
    base_raw = feedback.get("performance_score")
    if not isinstance(base_raw, (int, float)):
        base_raw = feedback.get("success_rate")
    if not isinstance(base_raw, (int, float)):
        base_raw = 0.5
    base = max(0.0, min(1.0, float(base_raw)))
    setpoints = SYSTEM_SETPOINTS.get(system_name, {})
    per_param: Dict[str, Any] = {}
    distances: List[float] = []
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
        per_param[param_name] = {
            "current": val_f, "setpoint": sp_f,
            "distance": round(distance, 4),
        }
    param_score = (1.0 - (sum(distances) / len(distances))) if distances else None
    score = (0.3 * base + 0.7 * param_score) if param_score is not None else base
    return {
        "system": system_name,
        "score": round(max(0.0, min(1.0, score)), 6),
        "weights": {"base": 0.3, "param_proximity": 0.7},
        "base_component": round(base, 6),
        "param_component": (round(param_score, 6)
                            if param_score is not None else None),
        "per_param": per_param,
        "calibration": None,  # F4 提案 gate 登记位：无校准记录＝出厂默认档
    }
