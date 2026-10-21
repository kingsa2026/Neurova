"""
数据流闭环检测（保留仍活的生命周期与情感/语音通道链路）。

D19 起，通道插件里的 threshold/centroid/weight/processor/temporal/moe_router
六档未接旋钮已退役；对应的旧闭环测试随实现一并删除。这里保留：
1. Agent 初始化→子系统→生命周期
2. 情感分析→记忆关联
"""
import pytest
import tempfile
from unittest.mock import MagicMock, patch


class TestAgentLifecycleFlow:
    """Agent 生命周期数据流闭环"""

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

    def test_agent_init_all_subsystems(self):
        """Agent初始化→所有子系统就绪"""
        agent = self._make_agent()
        # 核心子系统
        assert agent.config is not None
        assert agent.memory_agent is not None
        assert agent.context_orchestrator is not None
        assert agent.llm_client is not None
        assert agent.tool_executor is not None
        assert agent.post_chat_pipeline is not None
        assert agent.chat_pipeline is not None
        assert agent.loop_manager is not None

    def test_subsystem_container_groups(self):
        """SubSystemContainer 分组初始化"""
        from neurova.agent_core import SubSystemContainer
        agent = self._make_agent()
        assert hasattr(agent, '_subsystems')
        assert isinstance(agent._subsystems, SubSystemContainer)
        # 有所有初始化方法
        for method in ['init_memory', 'init_context', 'init_conversation',
                       'init_management', 'init_voice', 'init_security',
                       'init_cognition', 'init_evolution', 'init_tools',
                       'init_pipeline', 'init_loop']:
            assert hasattr(agent._subsystems, method)

    def test_agent_delegates_to_subsystems(self):
        """Agent 委托给子系统模块"""
        agent = self._make_agent()
        # context_orchestrator 有核心方法
        assert hasattr(agent.context_orchestrator, 'init_context_system')
        assert hasattr(agent.context_orchestrator, 'build_context')
        # tool_executor 有核心方法
        assert hasattr(agent.tool_executor, 'execute_from_memory_async')
        # chat_pipeline 有核心方法
        assert hasattr(agent.chat_pipeline, 'execute')


class TestEmotionMemoryFlow:
    """情感→记忆关联数据流闭环"""

    @pytest.mark.asyncio
    async def test_emotion_channel_filtering(self):
        """情感通道：无emotion_module→返回空"""
        from neurova.cognitive_layers.memory_layer.channels.builtin.emotion import EmotionChannel

        ch = EmotionChannel()
        mm = MagicMock()
        mm.emotion_module = None  # 无情感模块

        result = await ch.retrieve("happy query", memory_manager=mm)
        assert result == []

    @pytest.mark.asyncio
    async def test_voice_channel_filtering(self):
        """语音通道：筛选语音转写记忆"""
        from neurova.cognitive_layers.memory_layer.channels.builtin.voice import VoiceChannel

        ch = VoiceChannel()
        mm = MagicMock()
        mm.get_all_memories.return_value = [
            {"id": "v1", "content": "voice text", "memory_type": "asr_transcription",
             "metadata": {"record": {"confidence": 0.9, "engine": "whisper"}}},
            {"id": "v2", "content": "plain text", "memory_type": "text",
             "metadata": {}},
        ]

        result = await ch.retrieve("voice", memory_manager=mm)
        assert len(result) == 1
        assert result[0].memory_id == "v1"
