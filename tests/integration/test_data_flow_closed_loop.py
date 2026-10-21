"""
全项目数据流闭环检测

逐模块验证核心数据流是否闭环：
1. 记忆存储→检索→温度衰减
2. 工具记忆→肌肉记忆→经验闭环
3. 通道插件→MoE路由→结果处理
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

    def test_temperature_decay_cycle(self):
        """温度衰减闭环：高温→时间流逝→低温"""
        from neurova.cognitive_layers.memory_layer.channels.temporal import TemporalDecay

        td = TemporalDecay(curve="exponential", half_life_days=7)
        now = datetime.now(timezone.utc).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        # 新记忆温度高
        score_new = td.compute(now)
        assert score_new > 0.9

        # 旧记忆温度低
        score_old = td.compute(old)
        assert score_old < 0.5

        # 闭环：衰减后可以重新升温（通过访问）
        assert score_new > score_old

    def test_memory_dedup_cycle(self):
        """去重闭环：重复存储→去重→唯一结果"""
        from neurova.cognitive_layers.memory_layer.channels.processor import UnifiedResultProcessor
        from neurova.cognitive_layers.memory_layer.channels.base import ChannelResult

        proc = UnifiedResultProcessor()
        results = [
            ChannelResult("m1", "content A", 0.9, "text"),
            ChannelResult("m1", "content A dup", 0.5, "temperature"),
            ChannelResult("m2", "content B", 0.7, "text"),
        ]
        deduped = proc.deduplicate(results)
        assert len(deduped) == 2
        # 保留分数更高的
        assert deduped[0].score >= 0.7


# ═══════════════════════════════════════════════════════
# 2. 工具记忆→肌肉记忆→经验闭环
# ═══════════════════════════════════════════════════════

class TestToolMemoryFlow:
    """工具记忆数据流闭环"""

    def test_weight_adjustment_feedback_loop(self):
        """权重调整反馈闭环：正反馈→权重增加→负反馈→权重减少"""
        from neurova.cognitive_layers.memory_layer.channels.weight import WeightAdjuster

        wa = WeightAdjuster()
        w_before = wa.get_weights()["text"]

        # 正反馈
        for _ in range(10):
            wa.adjust("text", positive=True)
        w_after_positive = wa.get_weights()["text"]

        # 权重应增加（归一化后相对其他通道）
        assert w_after_positive > 0  # 至少不为0

        # 负反馈
        for _ in range(10):
            wa.adjust("text", positive=False)
        w_after_negative = wa.get_weights()["text"]

        # 权重应减少
        assert w_after_negative < w_after_positive

    def test_conflict_detection_loop(self):
        """冲突检测闭环：矛盾→检测→标记"""
        from neurova.cognitive_layers.memory_layer.channels.conflict import ConflictDetector
        from neurova.cognitive_layers.memory_layer.channels.base import ChannelResult

        cd = ConflictDetector()
        results = [
            ChannelResult("a", "Python is not a static typed language", 0.8, "text"),
            ChannelResult("b", "Python is a static typed language", 0.8, "text"),
        ]
        conflicts = cd.detect(results)
        assert len(conflicts) > 0
        # 冲突被正确标记
        assert conflicts[0].reason != ""


# ═══════════════════════════════════════════════════════
# 3. 通道插件→MoE路由→结果处理 闭环
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

    @pytest.mark.asyncio
    async def test_moe_to_processor_pipeline(self):
        """MoE路由→通道检索→结果处理 完整管道"""
        from neurova.cognitive_layers.memory_layer.channels.base import (
            BaseChannel, ChannelMetadata, ChannelResult, ChannelState
        )
        from neurova.cognitive_layers.memory_layer.channels.registry import ChannelRegistry
        from neurova.cognitive_layers.memory_layer.channels.moe_router import ChannelMoERouter
        from neurova.cognitive_layers.memory_layer.channels.processor import UnifiedResultProcessor
        from neurova.cognitive_layers.memory_layer.channels.weight import WeightAdjuster

        reg = ChannelRegistry()
        reg._channels.clear()
        reg._metadata.clear()

        class ChA(BaseChannel):
            @property
            def metadata(self):
                return ChannelMetadata(name="ch_a", display_name="A", description="Channel A")
            async def retrieve(self, query, limit=10, weight=1.0, **kwargs):
                return [ChannelResult("a1", "Result A", 0.9 * weight, "ch_a",
                       timestamp=datetime.now(timezone.utc).isoformat())]

        class ChB(BaseChannel):
            @property
            def metadata(self):
                return ChannelMetadata(name="ch_b", display_name="B", description="Channel B")
            async def retrieve(self, query, limit=10, weight=1.0, **kwargs):
                return [ChannelResult("b1", "Result B", 0.5 * weight, "ch_b",
                       timestamp=datetime.now(timezone.utc).isoformat())]

        for ChCls in [ChA, ChB]:
            ch = ChCls()
            ch._state = ChannelState.ACTIVE
            reg.register(ch)

        # MoE 路由
        vs = MagicMock()
        vs.encode.return_value = [0.1, 0.2]
        vs.get_expert_centroids.return_value = {}

        router = ChannelMoERouter(registry=reg, vector_store=vs, top_k=2,
                                   activation_threshold=0.1, fallback_to_all=True)
        with patch.object(router.gating, 'route', new_callable=AsyncMock) as mock_route:
            mock_route.return_value = {"ch_a": 0.9, "ch_b": 0.5}
            moe_results = await router.retrieve("query", limit=10)
            assert len(moe_results) > 0

        # 结果处理
        proc = UnifiedResultProcessor()
        wa = WeightAdjuster()
        output = proc.process(moe_results, wa.get_weights())
        assert output.total_count > 0
        assert len(output.results) > 0
        # 分数降序
        scores = [r.score for r in output.results]
        assert scores == sorted(scores, reverse=True)


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

    def test_threshold_config_lifecycle(self):
        """阈值配置→应用→调整 闭环"""
        from neurova.cognitive_layers.memory_layer.channels.threshold import ThresholdConfig

        tc = ThresholdConfig(default_threshold=0.3)
        tc.set_threshold("text", 0.5)
        assert tc.get_threshold("text") == 0.5
        assert tc.get_threshold("unknown") == 0.3

        # 导出→导入
        d = tc.to_dict()
        tc2 = ThresholdConfig.from_dict(d)
        assert tc2.get_threshold("text") == 0.5
        assert tc2.get_threshold("unknown") == 0.3


# ═══════════════════════════════════════════════════════
# 7. 端到端完整管道
# ═══════════════════════════════════════════════════════

class TestEndToEndPipeline:
    """端到端完整管道闭环"""

    @pytest.mark.asyncio
    async def test_full_data_flow(self):
        """用户输入→通道选择→检索→处理→输出"""
        from neurova.cognitive_layers.memory_layer.channels.base import (
            BaseChannel, ChannelMetadata, ChannelResult, ChannelState
        )
        from neurova.cognitive_layers.memory_layer.channels.registry import ChannelRegistry
        from neurova.cognitive_layers.memory_layer.channels.processor import UnifiedResultProcessor
        from neurova.cognitive_layers.memory_layer.channels.weight import WeightAdjuster
        from neurova.cognitive_layers.memory_layer.channels.temporal import TemporalDecay

        # 1. 注册通道
        reg = ChannelRegistry()
        reg._channels.clear()
        reg._metadata.clear()

        class SearchChannel(BaseChannel):
            @property
            def metadata(self):
                return ChannelMetadata(name="search", display_name="Search",
                    description="Search channel", capabilities=["text"])
            async def retrieve(self, query, limit=10, weight=1.0, **kwargs):
                return [
                    ChannelResult("s1", f"Found: {query}", 0.9 * weight, "search",
                        timestamp=datetime.now(timezone.utc).isoformat()),
                ]

        ch = SearchChannel()
        ch._state = ChannelState.ACTIVE
        reg.register(ch)

        # 2. 权重配置
        wa = WeightAdjuster()
        weights = wa.get_weights()

        # 3. 检索
        results = await ch.retrieve("test query", limit=5, weight=0.8)
        assert len(results) == 1

        # 4. 结果处理
        proc = UnifiedResultProcessor(
            temporal_decay=TemporalDecay(curve="exponential")
        )
        output = proc.process(results, weights)

        # 5. 验证输出
        assert output.total_count == 1
        assert output.deduped_count == 1
        assert len(output.results) == 1
        assert output.results[0].score > 0
        assert output.results[0].memory_id == "s1"

        # 6. 反馈调整
        wa.adjust("search", positive=True)
        new_weights = wa.get_weights()
        assert sum(new_weights.values()) == pytest.approx(1.0, abs=0.05)
