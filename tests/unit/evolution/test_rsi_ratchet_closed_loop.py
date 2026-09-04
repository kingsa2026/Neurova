"""棘轮剪枝闭环全链路 TDD 测试。

负责验证三个 RED（当前尚未通过）：
1. 所有候选无效时，pruner 应返回 None（当前返回 score=0 的候选）
2. 全链路闭环：工具执行 → 权重更新 → 经验反馈 → 模式挖掘 → 技能封装 → SkillRegistry
3. RSI 迭代能真实改善 ToolMemoryIntegration 参数（向 setpoint 收敛）
"""

import pytest

from neurova.evolution.rsi.recursive_ratchet_pruner import RecursiveRatchetPruner, Candidate
from neurova.evolution.closed_loop import get_evolution_orchestrator, reset_evolution_orchestrator
from neurova.evolution.skill_encapsulation import AutoSkillBuilder
from neurova.skills.registry import SkillRegistry


# ====================================================================
# RED-1: 所有候选无效时 pruner 应返回 None
# ====================================================================

def test_pruner_returns_none_when_all_candidates_invalid():
    """所有候选细筛得分为 0 时, recursive_prune 应返回 None.

    当前行为: 返回第一个候选, score=0.000 (RED).
    期望行为: 返回 None (GREEN).
    """
    pruner = RecursiveRatchetPruner()
    cands = [
        Candidate(id="c1", name="p", parameters={"p": 0.5}, complexity=0.1, heuristic_score=1.0),
        Candidate(id="c2", name="p", parameters={"p": 0.6}, complexity=0.1, heuristic_score=0.9),
    ]

    def heuristic_fn(c):
        return c.heuristic_score

    def quick_eval_fn(c):
        return 1.0 - c.complexity

    def validation_fn(c):
        return {"valid": False, "score": 0.0, "details": "all bad"}

    result = pruner.recursive_prune(
        cands, heuristic_fn=heuristic_fn, quick_eval_fn=quick_eval_fn, validation_fn=validation_fn
    )
    assert result is None, f"所有候选无效时应返回 None, 实际 {result.id if result else None} score={result.validation_score if result else None}"


def test_pruner_returns_valid_when_mixed():
    """混合有效/无效候选时, 有效者应获胜(回归测试)."""
    pruner = RecursiveRatchetPruner()

    cands = [
        Candidate(id="c_bad", name="p", parameters={"p": 0.5}, complexity=0.1, heuristic_score=1.0),
        Candidate(id="c_good", name="p", parameters={"p": 0.6}, complexity=0.1, heuristic_score=1.0),
    ]

    def heuristic_fn(c):
        return c.heuristic_score

    def quick_eval_fn(c):
        return 1.0 - c.complexity

    def validation_fn(c):
        valid = c.id != "c_bad"
        return {"valid": valid, "score": 1.0 if valid else 0.0, "details": ""}

    result = pruner.recursive_prune(
        cands, heuristic_fn=heuristic_fn, quick_eval_fn=quick_eval_fn, validation_fn=validation_fn
    )
    assert result is not None
    assert result.id == "c_good", f"无效候选不应胜出, 实际 {result.id}"


# ====================================================================
# RED-2: 全链路闭环真正生效
# ====================================================================

@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_evolution_orchestrator()
    yield
    reset_evolution_orchestrator()


def test_closed_loop_exec_weight_pattern_skill_registry():
    """闭环: 工具执行 → 权重更新 → 经验记录 → 模式挖掘 → 技能封装 → SkillRegistry.

    验证整条链路的数据流动, 而非各组件孤立测试.
    """
    # 1. 创建演化编排器
    orch = get_evolution_orchestrator()
    weights = orch.tool_weights
    lifecycle = orch.tool_lifecycle
    pattern_miner = orch.pattern_miner
    experience_feedback = orch.experience_feedback

    # 2. 注册工具
    tool_names = ["search_tool", "file_read_tool", "web_tool"]
    orch.register_tools(tool_names)
    for t in tool_names:
        weights.register_tool(t)

    # 3. 模拟工具执行（闭环第一环: 执行 → 权重/生命周期更新）
    orch.on_after_tool_execution("search_tool", success=True, latency=0.3)
    orch.on_after_tool_execution("file_read_tool", success=True, latency=0.5)
    orch.on_after_tool_execution("web_tool", success=True, latency=0.4)

    # 验证权重已更新
    for t in tool_names:
        w = weights.get_effective_weight(t)
        assert w > 0.5, f"{t} 权重应已更新, 实际 {w}"

    # 4. 模拟经验记录（闭环第二环: 经验反哺）
    result = orch.on_experience_recorded(
        text="成功完成搜索任务, 使用 search_tool 和 file_read_tool 读取文件",
        task="搜索文件",
        tools=tool_names[:2],
        success=True,
    )
    assert result["tools_mentioned"], f"经验应提取到工具, 实际 {result}"

    # 5. 模式挖掘（闭环第三环: 序列 → 频繁模式）
    pattern_miner.add_sequence(tool_names)
    pattern_miner.add_sequence(tool_names[:2])
    patterns = pattern_miner.mine()
    assert len(patterns) > 0, f"应有模式被挖掘, 实际 {len(patterns)}"

    # 6. 技能封装（闭环第四环: 模式 → 技能模板）
    skill_builder = AutoSkillBuilder(min_pattern_occurrences=2, min_success_rate=0.0)
    for p in patterns:
        # pattern.support 表示该序列出现了多少次；封装需要观察到 min_occurrences 次
        for _ in range(max(1, p.support)):
            skill_builder.observe(
                tool_sequence=p.tools,
                context="自动挖掘",
                success=True,
                duration=0.0,
            )
    templates = skill_builder.get_all_templates()
    assert len(templates) > 0, f"应有技能被封装, 实际 {len(templates)}"

    # C10 评审闸：产物默认 pending，注册前先批准全部待审模板
    for _t in skill_builder.list_pending_templates():
        assert skill_builder.approve_template(_t["template_id"])

    # 7. 注册到 SkillRegistry（闭环第五环: 技能入库, 供下次对话使用）
    registry = SkillRegistry()
    registered = skill_builder.register_to_skill_registry(registry)
    assert registered > 0, f"应成功注册技能, 实际 {registered}"
    assert len(registry.list_skills()) > 0, "注册表应为非空"


def test_genetic_engine_registers_to_skill_registry():
    """遗传引擎的高适应度工具应能成功注册到 SkillRegistry."""
    orch = get_evolution_orchestrator()
    from neurova.evolution.genetic_engine import ToolGenotype

    gen = orch.genetic_engine
    gen.add_to_population(
        ToolGenotype(
            tool_sequence=["search_tool", "file_read_tool"],
            success_rate=0.9,
            reuse_count=10,
        )
    )

    registry = SkillRegistry()
    registered = gen.register_to_skill_registry(registry)
    assert registered > 0, f"高适应度工具应注册到 SkillRegistry, 实际 {registered}"


# ====================================================================
# RED-3: RSI 真实改善 ToolMemory 参数
# ====================================================================

def test_rsi_closedloop_real_toolmemory_convergence():
    """RSI 迭代应真实改善 ToolMemoryIntegration 参数向 setpoint 收敛.

    这验证的是"真实系统实际改善"而非 Mock 系统.
    """
    from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
    from neurova.evolution.experience_feedback import ExperienceFeedback
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
    from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    # 创建真实系统（非 Mock）
    sleep = SleepConsolidation()
    emotion = EmotionModule()
    experience = ExperienceFeedback(known_tools=["search_tool", "file_tool"])
    tm = ToolMemoryIntegration()

    # 设置初始参数偏离 setpoint
    # tool_memory setpoints: success_bonus=0.1, failure_penalty=0.5, decay_rate=0.1, muscle_memory_threshold=0.8
    tm.success_bonus = 0.8  # 远离 0.1
    tm.failure_penalty = 0.9  # 远离 0.5
    tm.decay_rate = 0.3  # 远离 0.1

    orch = RSIOrchestrator(
        sleep_system=sleep,
        emotion_system=emotion,
        experience_system=experience,
        tool_memory_system=tm,
    )
    orch.deployment_controller._current_phase = 2

    # 执行足够多迭代
    gains = []
    for _ in range(15):
        if not orch.should_continue():
            break
        res = orch.run_iteration()
        gains.append(res.get("gain", 0.0))

    # 参数应朝 setpoint 移动（成功改善）
    assert tm.success_bonus < 0.8, f"success_bonus 应朝 0.1 收敛, 实际 {tm.success_bonus}"
    assert tm.failure_penalty < 0.9, f"failure_penalty 应朝 0.5 收敛, 实际 {tm.failure_penalty}"
    assert tm.decay_rate < 0.3, f"decay_rate 应朝 0.1 收敛, 实际 {tm.decay_rate}"

    # 至少有一次正增益（改善被保留）
    assert max(gains) > 0.0, f"应至少一次正增益, 实际 {gains}"


def test_rsi_real_system_four_signals():
    """真实系统 RSI 应收集全部 4 个系统的反馈信号."""
    from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
    from neurova.evolution.experience_feedback import ExperienceFeedback
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
    from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    orch = RSIOrchestrator(
        sleep_system=SleepConsolidation(),
        emotion_system=EmotionModule(),
        experience_system=ExperienceFeedback(),
        tool_memory_system=ToolMemoryIntegration(),
    )

    signals = orch.collect_feedback_signals()
    for sys_name in ("sleep", "emotion", "experience", "tool_memory"):
        assert sys_name in signals, f"缺少系统 {sys_name}"
        assert "performance_score" in signals[sys_name], f"{sys_name} 应注入 performance_score"
        score = signals[sys_name]["performance_score"]
        assert isinstance(score, float) and 0.0 <= score <= 1.0, f"performance_score 应为 [0,1], 实际 {score}"


# ====================================================================
# RED-4: RSI 优化的 memory 参数必须真正影响系统行为
# ====================================================================

def test_muscle_memory_threshold_affects_dynamic_threshold():
    """RSI 优化的 muscle_memory_threshold 必须真正影响自动执行阈值.

    当前行为: _get_dynamic_threshold 硬编码用 confidence_threshold(0.8),
    RSI 调 muscle_memory_threshold 后系统行为不变 → 死参数, 闭环断裂 (RED).
    期望行为: 调低 muscle_memory_threshold 应降低动态阈值基准 (GREEN).
    """
    from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration

    # 无权重时, 阈值基准应跟随 muscle_memory_threshold
    mem_default = ToolMemoryIntegration()  # muscle_memory_threshold=0.8
    mem_low = ToolMemoryIntegration()
    mem_low.muscle_memory_threshold = 0.5  # 模拟 RSI 调低

    base_default = mem_default._get_dynamic_threshold("any_tool")
    base_low = mem_low._get_dynamic_threshold("any_tool")

    assert base_default == pytest.approx(0.8, abs=1e-6), f"默认基准应为 0.8, 实际 {base_default}"
    assert base_low < base_default, (
        f"调低 muscle_memory_threshold 应降低动态阈值基准, 实际 {base_low} vs {base_default}"
    )
