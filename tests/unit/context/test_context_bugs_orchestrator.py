"""
上下文功能 Bug 修复 RED 测试 — C-3 + C-4 + C-6（context 模块）

C-3: orchestrator.py:222-226 tool_memory_context 死代码
    根本原因：构建了 tool_memory_context（含 auto_execute_result + tool_decision），但从未注入 ContextPool
    影响：LLM 看不到工具记忆执行状态

C-4: context_facade.py:287-303 全局单例污染
    根本原因：_facade_instance 缓存第一个 agent_ref，后续传入不同 agent_ref 仍返回第一个
    影响：多 Agent 系统中第二个 Agent 拿到错误 facade

C-6: orchestrator.py:82-83 skill_registry 无 getattr 保护
    根本原因：return self._agent._skill_registry（直接访问），对比 line 99 growth_log_manager 用 getattr
    影响：未设置 _skill_registry 的 Agent 调用 build_tools_for_llm 抛 AttributeError
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestC3ToolMemoryContextInjection:
    """C-3: build_context 应将 tool_memory_context 注入到返回的 context 中"""

    @pytest.mark.asyncio
    async def test_c3_tool_memory_context_visible_in_output(self):
        """RED: tool_memory_result + auto_execute_result 应出现在 build_context 返回值中

        Bug C-3: orchestrator.py:222-226
        实际代码: 构建 tool_memory_context 后从未 add_context 到 ContextPool
        """
        from neurova.context.orchestrator import ContextOrchestrator

        # 构造 mock agent
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.llm_model = "gpt-4"
        mock_agent.config.agent_id = "test_agent"
        mock_agent.soul = "Test Soul"
        mock_agent.personality = "Test Personality"
        mock_agent.constitution = "Test Constitution"
        mock_agent.developer_rules = ["Rule 1"]
        mock_agent.tool_router = None
        mock_agent._skill_registry = None
        mock_agent.growth_log_manager = None
        mock_agent.context_builder = None
        mock_agent.conversation_history = []
        mock_agent.memory_manager = None

        orch = ContextOrchestrator(mock_agent, use_pool=True)
        # 强制初始化 context_pool
        orch.init_context_system()

        tool_memory_result = {"tool_name": "weather", "result": "晴天 25°C"}
        auto_execute_result = {"status": "ok", "data": "25°C"}

        context = await orch.build_context(
            user_input="今天天气",
            tool_memory_result=tool_memory_result,
            auto_execute_result=auto_execute_result,
            tool_decision="auto_executed",
        )

        # 将所有消息内容合并
        all_content = " ".join(str(m.get("content", "")) for m in context)

        # 验证 tool_memory_context 的关键字段出现在 context 中
        assert "weather" in all_content or "天气" in all_content, (
            f"RED C-3: tool_memory_result 未注入 context（tool_name 缺失）"
        )
        assert "25°C" in all_content or "25" in all_content, (
            f"RED C-3: auto_execute_result 未注入 context（结果缺失）"
        )


class TestC4ContextFacadeSingletonPollution:
    """C-4: get_context_facade 不应用全局单例污染多 Agent"""

    def test_c4_different_agents_get_different_facades(self):
        """RED: 不同 agent_ref 应得到不同 ContextFacade 实例

        Bug C-4: context_facade.py:287-303
        实际代码: _facade_instance 缓存第一个 agent，后续返回同一个
        """
        from neurova.context.context_facade import ContextFacade, get_context_facade, reset_context_facade

        reset_context_facade()

        agent_a = MagicMock()
        agent_a.config = MagicMock(agent_id="agent_a")
        agent_b = MagicMock()
        agent_b.config = MagicMock(agent_id="agent_b")

        facade_a = get_context_facade(agent_a)
        facade_b = get_context_facade(agent_b)

        # 应是不同实例
        assert facade_a is not facade_b, (
            "RED C-4: 不同 agent_ref 应得到不同 ContextFacade 实例（全局单例污染）"
        )
        # 应绑定不同 agent
        assert facade_a._agent is agent_a, "facade_a 应绑定 agent_a"
        assert facade_b._agent is agent_b, "facade_b 应绑定 agent_b（实际绑定 agent_a）"

        reset_context_facade()


class TestC6SkillRegistryGetattrProtection:
    """C-6: skill_registry 属性应用 getattr 保护，避免 AttributeError"""

    def test_c6_skill_registry_no_attribute_error(self):
        """RED: Agent 无 _skill_registry 属性时不应抛 AttributeError

        Bug C-6: orchestrator.py:82-83
        实际代码: return self._agent._skill_registry（直接访问）
        对比: line 99 growth_log_manager 用 getattr(self._agent, "growth_log_manager", None)
        """
        from neurova.context.orchestrator import ContextOrchestrator

        # 构造无 _skill_registry 属性的 Agent
        class FakeAgent:
            def __init__(self):
                self.config = MagicMock()
                self.config.llm_model = "gpt-4"
                self.config.agent_id = "fake"
                self.soul = ""
                self.personality = ""
                self.tool_router = None
                self.growth_log_manager = None
                self.context_builder = None
                self.conversation_history = []
                self.memory_manager = None
                # 故意不设置 _skill_registry
                # constitution / developer_rules 也省略

        fake_agent = FakeAgent()
        orch = ContextOrchestrator(fake_agent, use_pool=False)

        # bug 存在时抛 AttributeError: 'FakeAgent' object has no attribute '_skill_registry'
        try:
            result = orch.skill_registry
            # 应返回 None（getattr 默认值），而非抛 AttributeError
            assert result is None, f"无 _skill_registry 时应返回 None，实际 {result}"
        except AttributeError as e:
            pytest.fail(f"RED C-6: skill_registry 无 getattr 保护，抛 AttributeError: {e}")
