# -*- coding: utf-8 -*-
"""
P3-c agent_ref 代理收窄：轮次级状态显式 API 防回归网

背景：chat_pipeline / openai_loop / loops.base / tool_executor 等深度模块
直接读写 Agent 单例的私有属性（_turn_count/_current_reasoning/_tool_messages_list/
_current_user_*），私有下划线穿透导致契约不可见、改名即崩。

收窄语义（渐进，不改存储位置）：
- 轮次级状态经显式 property/method 暴露；存储仍在原属性（兼容既有读者）
- _record_tool_failure_lesson / _detect_content_loop 提供公有别名
- tool_executor 经显式 API 读请求级身份（getattr 旧路径保留为过渡）
"""
import pytest

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline


def _make_agent():
    """最小 Agent 桩：仅承载轮次级状态，不触发重初始化"""
    class _Agent:
        pass

    return _Agent()


class TestTurnLevelStateAPI:
    """Agent 轮次级状态显式 API"""

    def test_current_reasoning_roundtrip(self):
        from neurova.agent_core import Agent

        agent = Agent.__new__(Agent)
        agent.set_current_reasoning("思考中")
        assert agent.current_reasoning == "思考中"
        agent.set_current_reasoning(None)
        assert agent.current_reasoning is None

    def test_tool_messages_reset_and_extend(self):
        from neurova.agent_core import Agent

        agent = Agent.__new__(Agent)
        agent.reset_tool_messages()
        assert agent.get_tool_messages_snapshot() == []
        agent.append_tool_messages([{"type": "tool_call", "tool_name": "t1"}])
        agent.append_tool_messages([{"type": "tool_result", "tool_name": "t1"}])
        snapshot = agent.get_tool_messages_snapshot()
        assert [m["type"] for m in snapshot] == ["tool_call", "tool_result"]
        # 快照是副本：改快照不影响内部
        snapshot.clear()
        assert len(agent.get_tool_messages_snapshot()) == 2

    def test_turn_count_increment(self):
        from neurova.agent_core import Agent

        agent = Agent.__new__(Agent)
        assert agent.increment_turn_count() == 1
        assert agent.increment_turn_count() == 2

    def test_append_tool_event_self_heals(self):
        from neurova.agent_core import Agent

        agent = Agent.__new__(Agent)
        agent.append_tool_event({"type": "tools_degraded", "reason": "r"})
        assert agent._tool_events == [{"type": "tools_degraded", "reason": "r"}]
        # 损坏态（非列表）自愈为全新列表，不崩不串
        agent._tool_events = "corrupt"
        agent.append_tool_event({"type": "x"})
        assert agent._tool_events == [{"type": "x"}]

    def test_request_identity_roundtrip(self):
        from neurova.agent_core import Agent

        agent = Agent.__new__(Agent)
        agent.set_request_identity(user_input="hi", session_id="s1", user_id="u9")
        assert agent.current_user_input == "hi"
        assert agent.current_session_id == "s1"
        assert agent.current_user_id == "u9"

    def test_request_identity_defaults(self):
        from neurova.agent_core import Agent

        agent = Agent.__new__(Agent)
        agent.set_request_identity(user_input="hi")
        assert agent.current_session_id is None
        assert agent.current_user_id == "default"


class TestPublicAliases:
    """私有方法公有别名（渐进收窄：原私有名保留防既有调用崩溃）"""

    @pytest.mark.asyncio
    async def test_record_tool_failure_lesson_alias(self):
        from neurova.agent_core import Agent

        agent = Agent.__new__(Agent)
        calls = []

        async def fake(self2, tool_name, user_input, error_msg):
            calls.append((tool_name, user_input, error_msg))

        agent._record_tool_failure_lesson = fake.__get__(agent)
        await agent.record_tool_failure_lesson("t", "u", "e")
        assert calls == [("t", "u", "e")]

    def test_detect_content_loop_alias(self):
        from neurova.agent_core import Agent

        agent = Agent.__new__(Agent)
        agent._detect_content_loop = lambda contents, threshold=0.8: True
        assert agent.detect_content_loop(["a"]) is True


class TestChatPipelineViaAPI:
    """chat_pipeline 经显式 API 初始化轮次状态（不再直写私有属性）"""

    def test_init_agent_state_uses_api(self):
        pipeline = ChatPipeline.__new__(ChatPipeline)

        class _Agent:
            def __init__(self):
                self.current_reasoning = "sentinel"
                self._tool_messages_list = [{"stale": True}]
                self.current_user_input = None
                self.current_session_id = None
                self.current_user_id = "old"

            def set_current_reasoning(self, v):
                self.current_reasoning = v

            def reset_tool_messages(self):
                self._tool_messages_list = []

            def set_request_identity(self, user_input, session_id=None, user_id=None):
                self.current_user_input = user_input
                self.current_session_id = session_id
                self.current_user_id = user_id or "default"

        pipeline._agent = _Agent()
        ctx = ChatContext(
            user_input="问题",
            metadata={"user_id": "u7"},
        )
        ctx.session_id = "sess-1"
        pipeline._init_agent_state(ctx)

        assert pipeline._agent.current_reasoning is None
        assert pipeline._agent._tool_messages_list == []
        assert pipeline._agent.current_user_input == "问题"
        assert pipeline._agent.current_session_id == "sess-1"
        assert pipeline._agent.current_user_id == "u7"

    def test_step_activity_uses_increment_api(self):
        pipeline = ChatPipeline.__new__(ChatPipeline)

        class _Agent:
            def __init__(self):
                self.turns = 0
                self.config = type("C", (), {"agent_id": "a1"})()
                self._trajectory_recorder = None
                self.idle_tracker = None

            def increment_turn_count(self):
                self.turns += 1
                return self.turns

        pipeline._agent = _Agent()
        ctx = ChatContext(user_input="x")
        ctx.metadata = {"history": []}  # 走 caller_provided_history 分支避免 session_manager 依赖

        import asyncio
        asyncio.run(pipeline._step_activity_tracking(ctx))
        assert pipeline._agent.turns == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
