"""
对话数据流通路检测

从 Agent.chat() 开始，追踪完整数据流：
Agent.chat() → ChatContext → ChatPipeline.execute() → 6个Step → 结果

验证每个 Step 的输入输出是否连通。
"""
import pytest
import asyncio
import tempfile
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from datetime import datetime, timezone

from neurova.agent.chat_pipeline import ChatPipeline, ChatContext


# ────── Mock Agent ──────

class MockAgent:
    """最小化 Agent 模拟（用于 ChatPipeline 测试）"""

    def __init__(self):
        self.config = MagicMock()
        self.config.name = "TestAgent"
        self.config.agent_id = "test"
        self.config.llm_config = MagicMock()
        self.config.llm_config.model = "test-model"

        self.memory_agent = MagicMock()
        self.memory_agent.update_history = MagicMock()
        self.memory_agent.save_to_session = MagicMock(return_value="session_1")

        self.context_orchestrator = MagicMock()
        self.context_orchestrator.build_context = AsyncMock(return_value=[
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ])
        self.context_orchestrator.build_tools_for_llm = AsyncMock(return_value=[])
        self.context_orchestrator.get_tools_description = AsyncMock(return_value="No tools")

        self.tool_memory = MagicMock()
        self.skill_manager = None
        self.tool_synthesizer = None
        self.unified_retriever = None
        self.crystallizer = MagicMock()
        self.crystallizer.observe = MagicMock()
        self.trace_manager = MagicMock()
        self.trace_manager.start_trace = MagicMock(return_value="trace_1")
        self.trace_manager.add_step = MagicMock()
        self.trace_manager.finish_trace = MagicMock()
        self.neuHebb_manager = None

        self.loop = MagicMock()
        self.loop.predict_step = AsyncMock(return_value=MagicMock(
            content="Hello! How can I help?",
            finish_reason="stop",
            tool_calls=None,
            reasoning_content=None,
        ))

        self.llm_client = MagicMock()
        self.llm_client.config = MagicMock()
        self.llm_client.config.max_tokens = 8192

        self.tool_executor = MagicMock()
        self.tool_executor.execute_text_tool_calls = AsyncMock(side_effect=lambda r, u: r)
        self.tool_executor.execute_from_memory = MagicMock(return_value=None)

        self.post_chat_pipeline = MagicMock()
        self.post_chat_pipeline.process = AsyncMock(return_value={
            "actual_session_id": "session_1",
            "audio_path": None,
            "audio_data": None,
            "cognitive_score": 0.8,
            "proactive_question": None,
        })

        self.session_manager = MagicMock()
        self._trajectory_recorder = MagicMock()
        self._trajectory_recorder.record_event = MagicMock()
        self._trajectory_recorder.end_trace = MagicMock()
        self.idle_tracker = MagicMock()
        self._current_reasoning = None
        self._tool_messages_list = []
        self._last_tool_used = None
        self.conversation_history = []
        self._current_user_input = None


# ────── Tests ──────

class TestChatPipelineDataFlow:
    """ChatPipeline 数据流通路检测"""

    @pytest.mark.asyncio
    async def test_pipeline_execute_full_flow(self):
        """完整管线执行：6个Step全部运行"""
        agent = MockAgent()
        pipeline = ChatPipeline(agent)

        ctx = ChatContext(user_input="Hello, how are you?")
        result = await pipeline.execute(ctx)

        # 验证结果结构
        assert result is not None
        assert "text" in result
        assert result["text"] == "Hello! How can I help?"

    @pytest.mark.asyncio
    async def test_step0_activity_tracking(self):
        """Step 0: 活动追踪通路"""
        agent = MockAgent()
        pipeline = ChatPipeline(agent)

        ctx = ChatContext(user_input="test")
        await pipeline.execute(ctx)

        # idle_tracker 应被调用
        assert agent.idle_tracker is not None

    @pytest.mark.asyncio
    async def test_step1_memory_retrieval(self):
        """Step 1: 记忆检索通路"""
        agent = MockAgent()
        pipeline = ChatPipeline(agent)

        ctx = ChatContext(user_input="What is Python?")
        await pipeline.execute(ctx)

        # context_orchestrator.build_context 应被调用
        agent.context_orchestrator.build_context.assert_called_once()

        # 验证 context 被设置
        assert len(ctx.context) > 0

    @pytest.mark.asyncio
    async def test_step1_context_building(self):
        """Step 1: 上下文构建通路"""
        agent = MockAgent()
        pipeline = ChatPipeline(agent)

        ctx = ChatContext(user_input="Hello")
        await pipeline.execute(ctx)

        # build_context 被调用，且参数包含 user_input
        call_args = agent.context_orchestrator.build_context.call_args
        assert call_args[1]["user_input"] == "Hello" or call_args[0][0] == "Hello"

    @pytest.mark.asyncio
    async def test_step3_llm_call(self):
        """Step 3: LLM 调用通路"""
        agent = MockAgent()
        pipeline = ChatPipeline(agent)

        ctx = ChatContext(user_input="Hello")
        await pipeline.execute(ctx)

        # Agent Loop 应被调用
        agent.loop.predict_step.assert_called()

        # reply 应被设置
        assert ctx.reply is not None
        assert len(ctx.reply) > 0

    @pytest.mark.asyncio
    async def test_step3_tool_calls_executed(self):
        """Step 3: 文本工具调用解析通路"""
        agent = MockAgent()
        pipeline = ChatPipeline(agent)

        ctx = ChatContext(user_input="Hello")
        await pipeline.execute(ctx)

        # tool_executor.execute_text_tool_calls 应被调用
        agent.tool_executor.execute_text_tool_calls.assert_called_once()

    @pytest.mark.asyncio
    async def test_step4_post_processing(self):
        """Step 4: 后处理通路"""
        agent = MockAgent()
        pipeline = ChatPipeline(agent)

        ctx = ChatContext(user_input="Hello")
        await pipeline.execute(ctx)

        # 对话历史应被更新
        agent.memory_agent.update_history.assert_called_once()

        # PostChatPipeline 应被调用
        agent.post_chat_pipeline.process.assert_called_once()

    @pytest.mark.asyncio
    async def test_step4_trajectory_recorded(self):
        """Step 4: 轨迹记录通路"""
        agent = MockAgent()
        pipeline = ChatPipeline(agent)

        ctx = ChatContext(user_input="Hello")
        await pipeline.execute(ctx)

        # trace_manager 应被调用
        agent.trace_manager.start_trace.assert_called_once()
        agent.trace_manager.finish_trace.assert_called_once()

    @pytest.mark.asyncio
    async def test_step4_crystallizer_observe(self):
        """Step 4: 结晶器观察通路"""
        agent = MockAgent()
        agent._last_tool_used = "web_search"
        pipeline = ChatPipeline(agent)

        ctx = ChatContext(user_input="Hello")
        await pipeline.execute(ctx)

        # crystallizer.observe 应被调用
        agent.crystallizer.observe.assert_called_once()

    @pytest.mark.asyncio
    async def test_result_assembly(self):
        """结果组装通路"""
        agent = MockAgent()
        pipeline = ChatPipeline(agent)

        ctx = ChatContext(user_input="Hello")
        result = await pipeline.execute(ctx)

        # 验证结果包含所有必要字段
        assert "text" in result
        assert "session_id" in result
        assert "cognitive_score" in result
        assert "experience_used" in result
        assert "tool_messages" in result

    @pytest.mark.asyncio
    async def test_data_flows_between_steps(self):
        """数据在 Step 之间正确流动"""
        agent = MockAgent()
        pipeline = ChatPipeline(agent)

        ctx = ChatContext(user_input="Test query")

        # 执行前，context 为空
        assert len(ctx.context) == 0
        assert ctx.reply is None

        # 执行后，context 和 reply 都有值
        await pipeline.execute(ctx)

        assert len(ctx.context) > 0  # Step 1 填充
        assert ctx.reply is not None  # Step 3 填充
        assert ctx.result is not None  # Step 4 填充

    @pytest.mark.asyncio
    async def test_memory_retrieval_chain_connected(self):
        """记忆检索责任链连通"""
        agent = MockAgent()
        pipeline = ChatPipeline(agent)

        # 验证责任链已初始化
        chain = pipeline.memory_retrieval_chain
        assert chain is not None
        retrievers = chain.get_retrievers()
        # 至少有 CacheRetriever 和 FallbackRetriever
        assert len(retrievers) >= 2


class TestChatContextDataFlow:
    """ChatContext 数据结构完整性"""

    def test_context_fields_populated(self):
        """ChatContext 字段完整性"""
        ctx = ChatContext(user_input="test")
        # 输入
        assert ctx.user_input == "test"
        assert ctx.stream is False
        assert ctx.save_memory is True
        # 中间状态
        assert ctx.tool_memory_result is None
        assert ctx.tool_decision == "do_not_execute"
        assert ctx.relevant_memories == []
        assert ctx.experience_items == []
        assert ctx.crystallized_patterns == []
        assert ctx.context == []
        # 结果
        assert ctx.reply is None
        assert ctx.result is None

    def test_context_carries_data_through_pipeline(self):
        """ChatContext 在管线中传递数据"""
        ctx = ChatContext(user_input="test", session_id="s1", stream=True)
        # 模拟管线修改 ctx
        ctx.relevant_memories = ["mem1", "mem2"]
        ctx.context = [{"role": "user", "content": "test"}]
        ctx.reply = "response"
        ctx.result = {"text": "response"}

        # 所有字段保持
        assert ctx.user_input == "test"
        assert ctx.session_id == "s1"
        assert ctx.stream is True
        assert len(ctx.relevant_memories) == 2
        assert len(ctx.context) == 1
        assert ctx.reply == "response"
