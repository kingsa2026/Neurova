"""认知三链路巡检 P0-2/B5 防回归：Agent 轮次与会话身份的读写契约。

根因：increment_turn_count 写 self._turn_count，而生产读取方全部
getattr(agent, "turn_count", 0)——实例无该属性恒得 0，导致
"每 10 轮自动反思/巩固门控"（post_chat_pipeline.py:1989/2001）、
RecallLoopGuard 轮次重置（tool_executor.py:2110）等 5 个挂点全灭。
session_id 同病：写入方用 getattr(agent, "session_id")，实际属性是
_current_session_id（agent_core.py），EKB 溯源恒 NULL。
"""
import pytest

from neurova.agent_core import Agent, AgentConfig


@pytest.fixture
def agent(tmp_path):
    cfg = AgentConfig(
        name="audit-agent",
        agent_id="audit-turn-count",
        workspace_path=str(tmp_path / "ws"),
    )
    return Agent(cfg)


def test_turn_count_property_reflects_increment(agent):
    """读取侧 getattr(agent, "turn_count") 必须等于 increment 后的真值。"""
    assert getattr(agent, "turn_count", 0) == 0
    agent.increment_turn_count()
    agent.increment_turn_count()
    assert getattr(agent, "turn_count", 0) == 2, (
        "turn_count 属性失配会让 post_chat_pipeline 的每10轮门控永假"
    )


def test_session_id_property_readable(agent):
    """session_id 可读（默认空串），_current_session_id 赋值后属性跟随。"""
    assert getattr(agent, "session_id", None) is not None
    agent._current_session_id = "sess-abc"
    assert agent.session_id == "sess-abc"
