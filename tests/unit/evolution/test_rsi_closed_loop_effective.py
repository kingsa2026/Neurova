"""
棘轮剪枝进化"真正闭环生效"验证（TDD 红绿）。

前一轮已修复机制缺陷（虚假收敛 / 失控漂移），但 RSI 仍"无效"：
- 真实 sleep/emotion 系统的 get_feedback() 不暴露任何性能键
  → 其参数（base_decay_rate / similarity_threshold / merge_threshold /
     emotional_protection_*）永不被优化；
- tool_memory/experience 暴露 success_rate，但是滚动统计，与记忆参数无即时
  因果关联 → 调整后实测增益≈0，棘轮只能"收敛于无收益"。
- 且棘轮只按硬编码方向单向移动、从不回滚有害调整。

本文件验证修复后的"真正闭环"：
1. 四个系统都能注入参数感知 performance_score（sleep/emotion 也能被优化）；
2. 性能分随参数变化（存在梯度，棘轮能发现改善方向）；
3. 端到端：参数偏离 setpoint 时，RSI 实测改善并保留（增益>0），参数朝 setpoint 移动；
4. 有害/无效调整被回滚（真棘轮：只保留有实测收益的调整）。
"""

from unittest.mock import Mock

from neurova.evolution.rsi.orchestrator import RSIOrchestrator
from neurova.evolution.rsi.integration_manager import RSIIntegrationManager
from neurova.evolution.rsi.system_performance import estimate_system_performance


def _mock_system(name, feedback, params):
    """构造带真实形状反馈（不含 performance_score）与可优化属性的桩。"""
    m = Mock()
    m.get_feedback = Mock(return_value=dict(feedback))
    for k, v in params.items():
        setattr(m, k, v)
    return m


def _build_orchestrator(sleep, emotion, experience, tool_memory, initial_phase=0):
    orch = RSIOrchestrator(sleep, emotion, experience, tool_memory)
    orch.deployment_controller._current_phase = initial_phase
    return orch


# ============ 1. 四系统均能被注入可优化性能信号 ============

def test_collect_feedback_injects_performance_for_all_systems():
    """integration_manager 应为四个系统都注入 0..1 的 performance_score，
    即便真实 sleep/emotion 的 get_feedback() 根本不含性能键（这是此前它们永不被优化的根因）。"""
    sleep = _mock_system("sleep", {"consolidation_count": 10, "merge_rate": 0.0, "avg_temperature": 50.0}, {})
    emotion = _mock_system("emotion", {"emotional_memories": 0, "avg_intensity": 0.0, "protection_triggered": 0}, {})
    experience = _mock_system("experience", {"crystallized_patterns": 2, "success_rate": 0.7}, {})
    tool_memory = _mock_system("tool_memory", {"total_usages": 5, "success_rate": 0.7, "muscle_memory_hits": 1}, {})

    integration = RSIIntegrationManager(sleep, emotion, experience, tool_memory)
    signals = integration.collect_feedback_signals()

    for sys_name in ("sleep", "emotion", "experience", "tool_memory"):
        assert "performance_score" in signals[sys_name], f"{sys_name} 应被注入 performance_score"
        score = signals[sys_name]["performance_score"]
        assert isinstance(score, float) and 0.0 <= score <= 1.0, f"{sys_name} 性能分应在 0..1，实际 {score}"


# ============ 2. 性能分随参数变化（存在梯度） ============

def test_performance_depends_on_parameters():
    """性能分应随参数偏离 setpoint 而下降、靠近而上升——否则棘轮无梯度、无法发现改善方向。"""
    feedback = {"merge_rate": 0.0, "avg_temperature": 50.0}
    at_setpoint = {"base_decay_rate": 0.1, "similarity_threshold": 0.8, "merge_threshold": 0.9}
    off_setpoint = dict(at_setpoint)
    off_setpoint["base_decay_rate"] = 0.5  # 远离 setpoint 0.1

    score_at = estimate_system_performance("sleep", feedback, at_setpoint)
    score_off = estimate_system_performance("sleep", feedback, off_setpoint)
    assert score_at > score_off, f"靠近 setpoint 应更高: at={score_at}, off={score_off}"


# ============ 3. 端到端：偏离 setpoint 的参数被实测改善并保留 ============

def test_rsi_improves_off_setpoint_parameter_end_to_end():
    """sleep.base_decay_rate 初始远离 setpoint(0.1)，RSI 应朝 setpoint 调整，
    且至少一次迭代产生正增益（改善被保留而非回滚）。"""
    sleep = _mock_system(
        "sleep",
        {"consolidation_count": 10, "merge_rate": 0.0, "avg_temperature": 50.0},
        {"base_decay_rate": 0.5, "similarity_threshold": 0.8, "merge_threshold": 0.9},
    )
    emotion = _mock_system(
        "emotion", {"emotional_memories": 0, "avg_intensity": 0.0, "protection_triggered": 0},
        {"emotional_protection_threshold": 0.5, "emotional_protection_factor": 1.0},
    )
    experience = _mock_system(
        "experience", {"crystallized_patterns": 2, "success_rate": 0.7},
        {"crystallize_min_observations": 3, "crystallize_min_success_rate": 0.6, "pattern_min_support": 2},
    )
    tool_memory = _mock_system(
        "tool_memory", {"total_usages": 5, "success_rate": 0.7, "muscle_memory_hits": 1},
        {"success_bonus": 0.1, "failure_penalty": 0.2, "decay_rate": 0.05, "muscle_memory_threshold": 0.8},
    )

    orch = _build_orchestrator(sleep, emotion, experience, tool_memory, initial_phase=2)
    initial_decay = sleep.base_decay_rate

    gains = []
    for _ in range(12):
        if not orch.should_continue():
            break
        res = orch.run_iteration()
        gains.append(res["gain"])

    # 改善被保留：至少一次正增益
    assert max(gains) > 0.0, f"应至少一次实测正增益（改善被保留），实际 gains={gains}"
    # 参数朝 setpoint(0.1) 移动：0.5 初始，应下降
    assert sleep.base_decay_rate < initial_decay, (
        f"base_decay_rate 应朝 setpoint 0.1 移动，实际 {initial_decay}→{sleep.base_decay_rate}"
    )


# ============ 4. 有害/无效调整被回滚（真棘轮） ============

def test_harmful_adjustment_is_reverted():
    """当所有参数已在 setpoint（任何移动都降低性能）时，应用后的实测增益≤0，
    RSI 必须把参数回滚到原值——否则棘轮会劣化系统（这正是"失控漂移"的本质）。"""
    params_all_at_setpoint = {
        "sleep": {"base_decay_rate": 0.1, "similarity_threshold": 0.8, "merge_threshold": 0.9},
        "emotion": {"emotional_protection_threshold": 0.5, "emotional_protection_factor": 1.0},
        "experience": {"crystallize_min_observations": 3, "crystallize_min_success_rate": 0.6, "pattern_min_support": 2},
        "tool_memory": {"success_bonus": 0.1, "failure_penalty": 0.2, "decay_rate": 0.05, "muscle_memory_threshold": 0.8},
    }
    sleep = _mock_system("sleep", {"consolidation_count": 10, "merge_rate": 0.0, "avg_temperature": 50.0}, params_all_at_setpoint["sleep"])
    emotion = _mock_system("emotion", {"emotional_memories": 0, "avg_intensity": 0.0, "protection_triggered": 0}, params_all_at_setpoint["emotion"])
    experience = _mock_system("experience", {"crystallized_patterns": 2, "success_rate": 0.7}, params_all_at_setpoint["experience"])
    tool_memory = _mock_system("tool_memory", {"total_usages": 5, "success_rate": 0.7, "muscle_memory_hits": 1}, params_all_at_setpoint["tool_memory"])

    orch = _build_orchestrator(sleep, emotion, experience, tool_memory, initial_phase=2)
    before = {
        "sleep.base_decay_rate": sleep.base_decay_rate,
        "emotion.emotional_protection_factor": emotion.emotional_protection_factor,
        "tool_memory.muscle_memory_threshold": tool_memory.muscle_memory_threshold,
    }

    orch.run_iteration()

    assert sleep.base_decay_rate == before["sleep.base_decay_rate"], "有害调整应被回滚"
    assert emotion.emotional_protection_factor == before["emotion.emotional_protection_factor"], "有害调整应被回滚"
    assert tool_memory.muscle_memory_threshold == before["tool_memory.muscle_memory_threshold"], "有害调整应被回滚"
