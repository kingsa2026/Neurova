"""M2 红灯：Skill 执行失败也必须进肌肉记忆降级链。

现状（修复前为红）：agent_core._on_skill_post_execute 对失败结果
（result is None or not result.success）提前 return——Skill 失败不进
on_tool_executed 的失败降级与自适应权重反馈链；而常规工具失败经
execute_tool 的 finally 统一进 on_tool_executed。

修复后契约：
- Skill 失败后，对应工具的肌肉记录 failure_count +1、连击归零；
- 自适应权重反馈 update_weight 收到 success=False；
- 成功路径行为不变（回归保护）。
"""

import pytest
from types import SimpleNamespace

from neurova.agent_core import Agent
from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory
from neurova.cognitive_layers.memory_layer.tool_memory_integration import (
    ToolMemoryIntegration,
)
from neurova.tool_executor import ToolExecutor


def _make_agent():
    """轻量 Agent（跳过重量级 __init__）+ 真实肌肉记忆链。"""
    agent = Agent.__new__(Agent)
    muscle = MuscleMemory()
    tmi = ToolMemoryIntegration(muscle_memory=muscle, muscle_memory_threshold=0.5)
    agent.tool_memory = tmi
    agent.tool_executor = ToolExecutor(agent)
    agent._current_user_input = "查一下明天天气"
    return agent, muscle, tmi


def _fail_result(**overrides):
    base = dict(
        success=False,
        execution_time=0.2,
        metadata={"skill_kwargs": {"city": "北京"}},
        error="上游服务超时",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _clear_turn_state():
    from neurova.core import turn_context

    turn_context.clear_turn_state()
    yield
    turn_context.clear_turn_state()


class TestSkillFailureEntersMuscleMemory:
    def test_failure_recorded_to_muscle_memory(self):
        """Skill 失败后：failure_count +1、连击归零（降级链入口）。"""
        agent, muscle, tmi = _make_agent()
        skill = SimpleNamespace(name="weather", config={})

        agent._on_skill_post_execute(skill, _fail_result())

        stats = tmi.get_tool_stats("weather")
        assert stats.get("fail", 0) == 1, (
            f"Skill 失败应记入工具记忆失败账，实际: {stats}"
        )
        matches = muscle.match_by_query("查一下明天天气")
        assert matches, "失败也应建条目（供降级链与后续观测）"
        item, _conf = matches[0]
        assert item.tool_name == "weather"
        assert item.failure_count == 1, (
            f"失败应使 failure_count+1，实际: {item.failure_count}"
        )
        assert item.consecutive_successes == 0, "失败应重置连击计数"

    def test_failure_drives_adaptive_weight_feedback(self):
        """失败应触发自适应权重反馈 update_weight(success=False)。"""
        agent, muscle, tmi = _make_agent()
        calls = []

        def _update_weight(tool_name, success, execution_time=0.0):
            calls.append((tool_name, success, execution_time))

        agent.evolution = SimpleNamespace(
            tool_weights=SimpleNamespace(update_weight=_update_weight)
        )
        skill = SimpleNamespace(name="weather", config={})

        agent._on_skill_post_execute(skill, _fail_result())

        assert calls, "失败必须触发 update_weight 反馈（原提前 return 漏记）"
        tool_name, success, _t = calls[0]
        assert tool_name == "weather"
        assert success is False

    def test_none_result_also_recorded_as_failure(self):
        """result is None 同样按失败入账（原条件覆盖的两个失败形态之一）。"""
        agent, muscle, tmi = _make_agent()
        skill = SimpleNamespace(name="weather", config={})

        agent._on_skill_post_execute(skill, None)

        stats = tmi.get_tool_stats("weather")
        assert stats.get("fail", 0) == 1, f"result=None 应按失败入账，实际: {stats}"

    def test_success_path_still_records_success(self):
        """回归保护：成功路径仍记成功（本修复不改变成功侧行为）。"""
        agent, muscle, tmi = _make_agent()
        skill = SimpleNamespace(name="weather", config={})
        result = SimpleNamespace(
            success=True, execution_time=0.1, metadata={"skill_kwargs": {}}
        )

        agent._on_skill_post_execute(skill, result)

        stats = tmi.get_tool_stats("weather")
        assert stats.get("success", 0) == 1, f"成功仍应记成功，实际: {stats}"
        assert stats.get("fail", 0) == 0
