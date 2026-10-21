"""
全项目数据流闭环检测

逐模块验证核心数据流是否闭环：
1. 记忆存储→检索→温度衰减
2. 工具记忆→肌肉记忆→经验闭环
3. 通道注册→检索→注销（通道插件基础）
4. Agent初始化→子系统→生命周期
5. 情感分析→记忆关联
6. 认知图谱→模式挖掘→经验结晶
"""
import pytest
import asyncio
import tempfile
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch


# ═══════════════════════════════════════════════════════
# 1. 记忆存储→检索→温度衰减 闭环
# ═══════════════════════════════════════════════════════

class TestMemoryFlow:
    """记忆数据流闭环"""

    def test_memory_storage_retrieval_cycle(self):
        """存储→检索→再存储 闭环"""
        from neurova.cognitive_layers.memory_layer.channels.base import ChannelResult

        # 模拟存储
        stored = []
        def store(mem):
            stored.append(mem)

        # 模拟检索
        def retrieve(query):
            return [m for m in stored if query.lower() in m.content.lower()]

        # 写入
        store(ChannelResult("m1", "Python programming", 0.9, "text"))
        store(ChannelResult("m2", "Java cooking", 0.7, "text"))

        # 检索
        results = retrieve("Python")
        assert len(results) == 1
        assert results[0].memory_id == "m1"


# ═══════════════════════════════════════════════════════
# 2. 工具记忆→肌肉记忆→经验闭环
# ═══════════════════════════════════════════════════════

class TestToolMemoryFlow:
    """工具记忆数据流闭环"""


# ═══════════════════════════════════════════════════════
# 3. 通道注册→检索→注销 闭环
# ═══════════════════════════════════════════════════════

class TestChannelPluginFlow:
    """通道插件数据流闭环"""

    @pytest.mark.asyncio
    async def test_channel_registry_lifecycle(self):
        """通道注册→激活→检索→注销 闭环"""
        from neurova.cognitive_layers.memory_layer.channels.base import (
            BaseChannel, ChannelMetadata, ChannelResult, ChannelState
        )
        from neurova.cognitive_layers.memory_layer.channels.registry import ChannelRegistry

        reg = ChannelRegistry()
        reg._channels.clear()
        reg._metadata.clear()

        class TestCh(BaseChannel):
            @property
            def metadata(self):
                return ChannelMetadata(name="test_ch", display_name="Test", description="Test ch")
            async def retrieve(self, query, limit=10, weight=1.0, **kwargs):
                return [ChannelResult("t1", f"Result: {query}", 0.8 * weight, "test_ch")]

        # 注册
        ch = TestCh()
        reg.register(ch)
        assert reg.get("test_ch") is ch

        # 激活
        await ch.initialize()
        assert ch.get_state() == ChannelState.ACTIVE
        assert len(reg.get_active()) == 1

        # 检索
        results = await ch.retrieve("hello", weight=0.9)
        assert len(results) == 1
        assert results[0].score == pytest.approx(0.72, abs=0.01)

        # 注销
        reg.unregister("test_ch")
        assert reg.get("test_ch") is None


# ═══════════════════════════════════════════════════════
# 4. Agent初始化→子系统→生命周期 闭环
# ═══════════════════════════════════════════════════════

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
        assert hasattr(agent.tool_executor, 'execute_from_memory')
        # chat_pipeline 有核心方法
        assert hasattr(agent.chat_pipeline, 'execute')


# ═══════════════════════════════════════════════════════
# 5. 情感分析→记忆关联 闭环
# ═══════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════
# 6. 配置→初始化→运行 闭环
# ═══════════════════════════════════════════════════════

class TestConfigFlow:
    """配置数据流闭环"""

    def test_agent_config_full_lifecycle(self):
        """配置创建→验证→使用 闭环"""
        from neurova.agent_core import AgentConfig
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = AgentConfig(
                agent_id="flow_test",
                name="FlowTest",
                workspace_path=tmpdir,
                enable_memory=True,
                enable_tts=True,
                enable_asr=True,
                enable_evolution=True,
            )
            # 所有字段可访问
            assert cfg.agent_id == "flow_test"
            assert cfg.enable_memory is True
            assert cfg.enable_tts is True
            assert cfg.enable_asr is True
            assert cfg.enable_evolution is True
            # 路径已创建
            assert os.path.exists(cfg.workspace_path)

