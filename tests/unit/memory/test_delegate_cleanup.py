"""
过渡性委托方法清理测试

验证清理后 Agent 的核心功能仍然正常。
"""
import pytest
import tempfile
from unittest.mock import MagicMock, AsyncMock, patch


class TestAgentDelegateCleanup:
    """验证委托方法清理后的行为"""

    def _make_agent(self):
        from neurova.agent_core import Agent, AgentConfig
        with patch.object(Agent, '_load_identity'), \
             patch.object(Agent, '_init_memory_modules'), \
             patch.object(Agent, '_init_cognitive_graph'):
            tmpdir = tempfile.mkdtemp()
            config = AgentConfig(
                agent_id="test", name="Test",
                workspace_path=tmpdir,
                enable_memory=False, enable_tts=False, enable_asr=False,
                enable_evolution=False, enable_experience_summary=False,
                enable_cognitive_capabilities=False,
            )
            return Agent(config=config)

    def test_removed_methods_not_exist(self):
        """已清理的方法不应存在"""
        agent = self._make_agent()
        removed = [
            '_init_file_operation_wrappers',
            '_init_agent_loop',
            '_execute_tool_from_memory',
            '_execute_tool_from_memory_async',
            '_execute_skill_tool',
            '_execute_cli_tool',
            '_get_builtin_tool_params',
            '_get_tools_description',
            '_build_system_prompt',
            '_update_history',
            '_save_conversation_memory',
            'get_memory_stats',
            '_chat_normal',
            '_chat_stream',
        ]
        for method in removed:
            assert not hasattr(agent, method), f"{method} 应已被移除"

    def test_on_tool_executed_inlined(self):
        """_on_tool_executed 已内联到 tool_executor"""
        agent = self._make_agent()
        # _on_tool_executed 不应再存在于 Agent 上
        assert not hasattr(agent, '_on_tool_executed')

    def test_save_to_session_preserved(self):
        """_save_to_session 保留（有外部调用者）"""
        agent = self._make_agent()
        assert hasattr(agent, '_save_to_session')

    def test_core_capabilities_intact(self):
        """核心能力不受影响"""
        agent = self._make_agent()
        # 核心属性
        assert hasattr(agent, 'config')
        assert hasattr(agent, 'memory_agent')
        assert hasattr(agent, 'context_orchestrator')
        assert hasattr(agent, 'tool_executor')
        assert hasattr(agent, 'chat_pipeline')
        assert hasattr(agent, 'loop_manager')
