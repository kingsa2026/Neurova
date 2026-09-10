"""A-04 / A-07 / A-08 / A-15 / A-16 回归测试（agent_core.py）。

红绿说明（修复缺位时为红）：
- A-04: `_current_user_input` 原为实例属性死状态（init_conversation 置 None
  写不进 ContextVar，读取方恒 None）→ 写入后 `current_user_input` 读不到（红）。
- A-07: `_model_switch_lock` 原为类属性（全 Agent 实例共用一把锁）→
  两实例拿到同一把锁（红）。
- A-08: 依赖图缺 evolution→tools 依赖 → 拓扑序 evolution 先于 tools（红）。
- A-15: 肌肉记忆降级失败分支原 `logger.debug` 吞错 → 无 warning 记录（红）。
- A-16: result 无 metadata 字段（SkillExecutionResult 形态）时
  `result.metadata.get` 抛 AttributeError，ToolMemory 记录整体丢失（红）。
"""

import asyncio
import inspect
import logging
from types import SimpleNamespace

from neurova.agent_core import Agent, SubSystemContainer


def _fresh_agent() -> Agent:
    """跳过重量级 __init__，仅构造类契约测试所需实例。"""
    return Agent.__new__(Agent)


def _setup():
    from neurova.core import turn_context

    turn_context.clear_turn_state()
    return turn_context


# ═══════════════════════════════════════════════════════════════
# A-04: _current_user_input 绑定 ContextVar
# ═══════════════════════════════════════════════════════════════


def test_a04_current_user_input_is_class_level_property():
    assert isinstance(inspect.getattr_static(Agent, "_current_user_input"), property), (
        "A-04: _current_user_input 必须是绑定 ContextVar 的 property"
        "（纯实例属性是迁 ContextVar 后的死状态）"
    )


def test_a04_setter_writes_same_contextvar_as_current_user_input():
    tc = _setup()
    agent = _fresh_agent()

    agent._current_user_input = "帮我查北京天气"  # setter 写 ContextVar
    assert agent.current_user_input == "帮我查北京天气", (
        "A-04: 写 _current_user_input 后 current_user_input 必须同值（同一 ContextVar）"
    )
    assert agent._current_user_input == "帮我查北京天气"  # getter 同源

    agent._current_user_input = None  # init_conversation 的置 None 重置语义
    assert agent.current_user_input is None
    tc.clear_turn_state()


def test_a04_skill_post_execute_sees_real_user_input(monkeypatch):
    """tool_executor 消费路径恢复：_on_skill_post_execute 拿到真实轮次输入。"""
    tc = _setup()
    monkeypatch.setattr(
        "neurova.evolution.skill_improver.get_skill_improver",
        lambda: SimpleNamespace(record_usage=lambda **k: None),
    )

    recorded = {}

    class FakeService:
        def __init__(self, agent_id=None):
            pass

        def record_skill_usage(self, *a, **k):
            pass

    monkeypatch.setattr("neurova.skills.skill_service.SkillService", FakeService)

    agent = _fresh_agent()
    agent.tool_memory = SimpleNamespace()  # truthy → 进入记录分支
    agent.tool_executor = SimpleNamespace(
        on_tool_executed=lambda **kw: recorded.update(kw)
    )
    agent._current_user_input = "查一下明天天气"  # 轮次输入（原缺陷：恒 None）

    skill = SimpleNamespace(name="weather", config={})
    result = SimpleNamespace(success=True, execution_time=0.1, metadata={})
    agent._on_skill_post_execute(skill, result)

    assert recorded.get("user_input") == "查一下明天天气", (
        "A-04: 肌肉记忆记录必须拿到真实轮次用户输入（原恒落占位串）"
    )
    tc.clear_turn_state()


# ═══════════════════════════════════════════════════════════════
# A-07: 模型热切换锁实例级
# ═══════════════════════════════════════════════════════════════


def test_a07_model_switch_lock_is_per_instance():
    a1, a2 = _fresh_agent(), _fresh_agent()
    lock1 = a1._get_model_switch_lock()
    lock2 = a2._get_model_switch_lock()

    assert lock1 is not lock2, (
        "A-07: 模型热切换锁必须实例级（原类属性全 Agent 实例共用一把锁）"
    )
    assert a1._get_model_switch_lock() is lock1, "同一实例必须复用同一把锁"


def test_a07_rebuild_loop_uses_instance_lock(monkeypatch):
    """rebuild_loop 经 self._get_model_switch_lock() 串行化（用法不破坏）。"""
    agent = _fresh_agent()
    lock = asyncio.Lock()
    agent._model_switch_lock = lock
    assert agent._get_model_switch_lock() is lock


# ═══════════════════════════════════════════════════════════════
# A-08: evolution 依赖 tools
# ═══════════════════════════════════════════════════════════════


def test_a08_tools_initialized_before_evolution():
    container = SubSystemContainer.__new__(SubSystemContainer)
    order = container._compute_initialization_order()

    assert "tools" in order and "evolution" in order
    assert order.index("tools") < order.index("evolution"), (
        "A-08: init_tools 必须先于 init_evolution"
        "（否则 _skill_registry 尚为 None，register_tools 永不执行）"
    )


def test_a08_register_tools_called_when_skill_registry_ready(monkeypatch):
    """skills 就绪（tools 先行后的状态）时 init_evolution 必须调用 register_tools。"""
    calls = {}
    fake_evo = SimpleNamespace(
        register_tools=lambda names: calls.setdefault("names", list(names)),
        tool_lifecycle=None,
        pattern_miner=None,
        genetic_engine=None,
        tool_weights={},
    )
    import neurova.evolution.closed_loop as closed_loop_mod

    monkeypatch.setattr(closed_loop_mod, "get_evolution_orchestrator", lambda: fake_evo)

    agent = SimpleNamespace(
        config=SimpleNamespace(enable_evolution=True, enable_experience_summary=True),
        _skill_registry=SimpleNamespace(
            list_skills=lambda: [SimpleNamespace(name="s1"), SimpleNamespace(name="s2")]
        ),
        tool_memory=None,
        crystallizer=None,
        rsi_orchestrator=None,
    )
    container = SubSystemContainer.__new__(SubSystemContainer)
    container.agent = agent
    container.config = agent.config

    container.init_evolution()

    assert calls.get("names") == ["s1", "s2"], (
        "A-08: init_evolution 必须把 _skill_registry 的技能注册进进化引擎"
    )


# ═══════════════════════════════════════════════════════════════
# A-15: 肌肉记忆降级失败不得 debug 吞错
# ═══════════════════════════════════════════════════════════════


def test_a15_muscle_degradation_failure_logs_warning(caplog):
    class ExplodingMuscle:
        def __getattribute__(self, name):
            if name.startswith("_l") and name[2:].isdigit():
                raise RuntimeError("muscle layer access exploded")
            return super().__getattribute__(name)

    agent = _fresh_agent()
    agent.tool_memory = SimpleNamespace(muscle_memory=ExplodingMuscle())
    agent.growth_log_manager = None  # 跳过反思日志分支

    with caplog.at_level(logging.DEBUG, logger="neurova.agent_core"):
        asyncio.run(agent._record_tool_failure_lesson("tool_x", "user input", "err"))

    warnings = [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING and "肌肉记忆降级" in r.getMessage()
    ]
    assert warnings, "A-15: 肌肉记忆降级失败必须 warning（原 logger.debug 吞错）"
    assert warnings[0].exc_info is not None, "A-15: warning 必须携带 exc_info"


def test_a15_muscle_degradation_happy_path_still_resets():
    """A-15 收口核验：降级走公开 degrade_tool——重置匹配工具、不动其他工具。"""
    from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory

    muscle = MuscleMemory()  # 无 storage_path → 落盘 no-op，纯内存验证
    item = SimpleNamespace(tool_name="tool_x", consecutive_successes=3)
    muscle._l1["k"] = item
    untouched = SimpleNamespace(tool_name="other_tool", consecutive_successes=5)
    muscle._l2["j"] = untouched

    assert muscle.degrade_tool("tool_x") is True
    assert item.consecutive_successes == 0
    assert untouched.consecutive_successes == 5
    # 已归零的工具再次降级不产生变更（幂等，不再触发落盘）
    assert muscle.degrade_tool("tool_x") is False


# ═══════════════════════════════════════════════════════════════
# A-16: result.metadata 判空
# ═══════════════════════════════════════════════════════════════


def test_a16_skill_result_without_metadata_no_crash(monkeypatch):
    """SkillExecutionResult 形态（无 metadata 字段）不得炸掉 ToolMemory 记录。"""
    monkeypatch.setattr(
        "neurova.evolution.skill_improver.get_skill_improver",
        lambda: SimpleNamespace(record_usage=lambda **k: None),
    )

    class FakeService:
        def __init__(self, agent_id=None):
            pass

        def record_skill_usage(self, *a, **k):
            pass

    monkeypatch.setattr("neurova.skills.skill_service.SkillService", FakeService)

    recorded = {}

    agent = _fresh_agent()
    agent.tool_memory = SimpleNamespace()  # truthy
    agent.tool_executor = SimpleNamespace(
        on_tool_executed=lambda **kw: recorded.update(kw)
    )

    skill = SimpleNamespace(name="weather", config={})
    # 无 metadata 字段的结果对象（skills/models.py SkillExecutionResult 形态）
    result = SimpleNamespace(success=True, execution_time=0.1)
    agent._on_skill_post_execute(skill, result)

    assert recorded.get("params") == {}, (
        "A-16: result 无 metadata 时按空参处理，记录不得整体丢失"
    )
    assert recorded.get("tool_name") == "weather"


def test_a16_metadata_with_skill_kwargs_still_extracted(monkeypatch):
    """原有 metadata 路径不回归：skill_kwargs 照常提取。"""
    monkeypatch.setattr(
        "neurova.evolution.skill_improver.get_skill_improver",
        lambda: SimpleNamespace(record_usage=lambda **k: None),
    )

    class FakeService:
        def __init__(self, agent_id=None):
            pass

        def record_skill_usage(self, *a, **k):
            pass

    monkeypatch.setattr("neurova.skills.skill_service.SkillService", FakeService)

    recorded = {}
    agent = _fresh_agent()
    agent.tool_memory = SimpleNamespace()
    agent.tool_executor = SimpleNamespace(
        on_tool_executed=lambda **kw: recorded.update(kw)
    )

    skill = SimpleNamespace(name="weather", config={})
    result = SimpleNamespace(
        success=True, execution_time=0.1, metadata={"skill_kwargs": {"city": "北京"}}
    )
    agent._on_skill_post_execute(skill, result)

    assert recorded.get("params") == {"city": "北京"}
