"""
Agent SubSystemContainer 重构测试

验证重构后 Agent 的所有子系统属性仍然可用。
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestAgentAttributes:
    """验证 Agent 初始化后所有关键属性存在"""

    def _make_agent(self):
        """创建最小化 Agent 实例（跳过真实初始化）"""
        from neurova.agent_core import Agent, AgentConfig
        import tempfile, os

        with patch.object(Agent, '_load_identity'), \
             patch.object(Agent, '_init_memory_modules'), \
             patch.object(Agent, '_init_cognitive_graph'):

            tmpdir = tempfile.mkdtemp()
            config = AgentConfig(
                agent_id="test_agent",
                name="TestAgent",
                workspace_path=tmpdir,
                enable_memory=False,
                enable_tts=False,
                enable_asr=False,
                enable_evolution=False,
                enable_experience_summary=False,
                enable_cognitive_capabilities=False,
            )
            agent = Agent(config=config)
            return agent

    def test_core_attributes_exist(self):
        """核心属性存在"""
        agent = self._make_agent()
        assert hasattr(agent, 'config')
        assert hasattr(agent, 'memory_manager')
        assert hasattr(agent, 'memory_agent')
        assert hasattr(agent, 'context_orchestrator')
        assert hasattr(agent, 'llm_client')

    def test_conversation_attributes_exist(self):
        """对话相关属性存在"""
        agent = self._make_agent()
        assert hasattr(agent, 'conversation_history')
        assert hasattr(agent, '_current_user_input')
        assert hasattr(agent, '_current_trace_id')

    def test_management_attributes_exist(self):
        """管理相关属性存在"""
        agent = self._make_agent()
        assert hasattr(agent, 'session_manager')
        assert hasattr(agent, 'sleep_config_manager')
        assert hasattr(agent, 'idle_tracker')

    def test_tool_attributes_exist(self):
        """工具相关属性存在"""
        agent = self._make_agent()
        assert hasattr(agent, 'tool_executor')
        assert hasattr(agent, 'post_chat_pipeline')
        assert hasattr(agent, 'chat_pipeline')

    def test_pipeline_attributes_exist(self):
        """管线属性存在"""
        agent = self._make_agent()
        assert hasattr(agent, 'tool_executor')
        assert hasattr(agent, 'post_chat_pipeline')
        assert hasattr(agent, 'chat_pipeline')

    def test_voice_attributes_exist(self):
        """语音属性存在（可能为 None）"""
        agent = self._make_agent()
        assert hasattr(agent, 'tts_manager')
        assert hasattr(agent, 'asr_manager')
        assert hasattr(agent, 'voice_pipeline')

    def test_evolution_attributes_exist(self):
        """进化属性存在（可能为 None）"""
        agent = self._make_agent()
        assert hasattr(agent, 'evolution')
        assert hasattr(agent, 'growth_analyzer')

    def test_loop_attributes_exist(self):
        """Loop 属性存在"""
        agent = self._make_agent()
        assert hasattr(agent, 'loop_manager')
        assert hasattr(agent, 'loop')


class TestSubSystemContainer:
    """SubSystemContainer 功能测试"""

    def test_container_groups_initialization(self):
        """容器将初始化分组"""
        from neurova.agent_core import SubSystemContainer

        agent = MagicMock()
        agent.config = MagicMock()
        agent.config.enable_memory = False
        agent.config.enable_tts = False
        agent.config.enable_asr = False
        agent.config.enable_evolution = False
        agent.config.enable_experience_summary = False
        agent.config.enable_cognitive_capabilities = False

        container = SubSystemContainer(agent)
        assert container.agent is agent
        assert container.config is agent.config

    def test_container_has_init_methods(self):
        """容器有各子系统初始化方法"""
        from neurova.agent_core import SubSystemContainer

        agent = MagicMock()
        container = SubSystemContainer(agent)

        assert hasattr(container, 'init_memory')
        assert hasattr(container, 'init_context')
        assert hasattr(container, 'init_voice')
        assert hasattr(container, 'init_tools')
        assert hasattr(container, 'init_evolution')
        assert hasattr(container, 'init_cognition')
        assert hasattr(container, 'init_all')
