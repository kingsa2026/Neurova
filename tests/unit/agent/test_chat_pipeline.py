"""
Tests for ChatPipeline — 对话流程管线

验证从 Agent.chat() 提取的管线步骤能正确执行。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from neurova.agent.chat_pipeline import ChatPipeline, ChatContext


@pytest.fixture
def mock_agent():
    """创建模拟的 Agent 实例"""
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.agent_id = "test-agent"
    agent.config.llm_config = MagicMock()
    agent.config.llm_config.model = "test-model"
    agent.config.name = "TestAgent"

    # 记忆模块
    agent.memory_agent = MagicMock()
    agent.memory_agent.update_history = MagicMock()
    # 修复: 检索链 initialize 走 getattr(memory_agent, "moe_router")，
    # MagicMock 的任意属性会被返回另一个 MagicMock（truthy）→ MoERetrieverAdapter
    # 拿到不可 await 的 router → "MagicMock can't be used in await"。
    # 显式给 moe_router 一个 AsyncMock.retrieve，或直接置为 None 跳过 MoE。
    moe_router = MagicMock()
    moe_router.retrieve = AsyncMock(return_value=[])
    agent.memory_agent.moe_router = moe_router

    # 上下文构建
    agent.context_orchestrator = MagicMock()
    agent.context_orchestrator.build_context = AsyncMock(return_value=[
        {"role": "system", "content": "test"},
        {"role": "user", "content": "hello"},
    ])
    agent.context_orchestrator.build_tools_for_llm = AsyncMock(return_value=[])

    # 工具执行
    agent.tool_executor = MagicMock()
    agent.tool_executor.execute_text_tool_calls = AsyncMock(side_effect=lambda r, u: r)
    agent.tool_executor.execute_from_memory_async = AsyncMock(return_value={"status": "success"})

    # 后处理管线
    agent.post_chat_pipeline = MagicMock()
    agent.post_chat_pipeline.process = AsyncMock(return_value={
        "actual_session_id": "test-session",
        "audio_path": None,
        "audio_data": None,
        "cognitive_score": 0.8,
        "proactive_question": None,
    })

    # 轨迹记录
    agent._trajectory_recorder = None
    agent._current_reasoning = None
    agent._tool_messages_list = []
    agent._current_user_input = None
    agent._turn_count = 0

    # 子系统
    agent.tool_memory = None
    agent.skill_manager = None
    agent.tool_synthesizer = None
    agent.unified_retriever = None
    # 修复: getattr(agent, "pipeline_executor") 在 MagicMock 上会返回新 MagicMock
    # （truthy）→ 走 executor 分支 await MagicMock.execute → fallback。
    # 显式 None 走 post_chat_pipeline 测试路径（与 integration_tdd fixture 一致）。
    agent.pipeline_executor = None
    agent.crystallizer = None
    agent.trace_manager = None
    agent.neuHebb_manager = None
    agent.idle_tracker = MagicMock()
    agent.session_manager = MagicMock()
    agent.loop = None
    agent.llm_client = MagicMock()
    agent.llm_client.config = MagicMock()
    agent.llm_client.config.max_tokens = 8192
    # 修复: chat 是异步方法, 必须用 AsyncMock 而非默认 MagicMock
    # 否则 await self.llm_client.chat(ctx.context) 抛 TypeError: 'MagicMock' object can't be awaited
    # 返回 dict 走 _call_legacy_normal 的 success 分支 (chat_pipeline.py:1035-1043)
    agent.llm_client.chat = AsyncMock(
        return_value={"success": True, "response": "Hello from legacy!"}
    )
    # chat_stream 返回异步迭代器, 走 _call_legacy_stream 的 async for 路径 (chat_pipeline.py:1055)
    # 契约: chunk 为 LLMResponse 对象（getattr(chunk, "content")），
    # 纯字符串会被 _call_legacy_stream 的 getattr(content) 判空丢弃 → 回复为空。
    # 用 SimpleNamespace 模拟 LLMResponse.content。
    from types import SimpleNamespace

    async def _async_iter():
        # yield 模拟流式 chunk（LLMResponse 契约）
        for chunk in ["Hello", " from ", "legacy!"]:
            yield SimpleNamespace(content=chunk)

    agent.llm_client.chat_stream = MagicMock(side_effect=lambda *a, **k: _async_iter())

    # Agent Loop
    agent._chat_normal = AsyncMock(return_value="Hello from legacy!")
    agent._chat_stream = AsyncMock(return_value="Hello from stream!")

    return agent


@pytest.fixture
def pipeline(mock_agent):
    """创建 ChatPipeline 实例"""
    return ChatPipeline(mock_agent)


@pytest.fixture
def ctx():
    """创建 ChatContext 实例"""
    return ChatContext(user_input="Hello, how are you?")


class TestChatContext:
    """ChatContext 数据类测试"""

    def test_default_values(self):
        ctx = ChatContext(user_input="test")
        assert ctx.user_input == "test"
        assert ctx.stream is False
        assert ctx.save_memory is True
        assert ctx.session_id is None
        assert ctx.tool_decision == "do_not_execute"
        assert ctx.relevant_memories == []
        assert ctx.experience_items == []
        assert ctx.crystallized_patterns == []

    def test_custom_values(self):
        ctx = ChatContext(
            user_input="test",
            stream=True,
            save_memory=False,
            session_id="sess-123",
        )
        assert ctx.stream is True
        assert ctx.save_memory is False
        assert ctx.session_id == "sess-123"


class TestChatPipeline:
    """ChatPipeline 主流程测试"""

    @pytest.mark.asyncio
    async def test_execute_returns_result(self, pipeline, ctx, mock_agent):
        """execute() 应返回包含 text 的字典"""
        result = await pipeline.execute(ctx)
        assert "text" in result
        assert result["text"] == "Hello from legacy!"

    @pytest.mark.asyncio
    async def test_execute_calls_update_history(self, pipeline, ctx, mock_agent):
        """execute() 应调用 memory_agent.update_history"""
        await pipeline.execute(ctx)
        mock_agent.memory_agent.update_history.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_calls_post_chat_pipeline(self, pipeline, ctx, mock_agent):
        """execute() 应调用 post_chat_pipeline.process"""
        await pipeline.execute(ctx)
        mock_agent.post_chat_pipeline.process.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_restores_session(self, pipeline, mock_agent):
        """execute() 应恢复 session 历史"""
        ctx = ChatContext(user_input="test", session_id="sess-123")
        mock_agent.session_manager.get_session = MagicMock(return_value=None)
        mock_agent.session_manager.get_recent_context = MagicMock(return_value=[])
        await pipeline.execute(ctx)
        mock_agent.session_manager.get_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_increments_turn_count(self, pipeline, ctx, mock_agent):
        """execute() 应递增对话轮次计数"""
        # P3-c 收窄：经 increment_turn_count 显式 API（MagicMock 自动记 5→6 次调用数不可靠，
        # 断言调用发生即可）
        await pipeline.execute(ctx)
        mock_agent.increment_turn_count.assert_called()

    @pytest.mark.asyncio
    async def test_execute_with_stream(self, pipeline, mock_agent):
        """流式模式应调用 llm_client.chat_stream

        更新: 旧 API 调用 _chat_stream, 新 API 调用 llm_client.chat_stream
        (chat_pipeline.py:1055 _call_legacy_stream)
        """
        mock_agent.loop = None  # Force legacy mode
        ctx = ChatContext(user_input="test", stream=True)
        result = await pipeline.execute(ctx)
        mock_agent.llm_client.chat_stream.assert_called_once()
        # 验证流式 chunk 被拼接
        assert result["text"] == "Hello from legacy!"

    @pytest.mark.asyncio
    async def test_execute_legacy_fallback(self, pipeline, ctx, mock_agent):
        """无 Agent Loop 时应 fallback 到 legacy 方法

        更新: 旧 API 调用 _chat_normal, 新 API 调用 llm_client.chat
        (chat_pipeline.py:1034 _call_legacy_normal)
        """
        mock_agent.loop = None
        result = await pipeline.execute(ctx)
        mock_agent.llm_client.chat.assert_called_once()
        assert result["text"] == "Hello from legacy!"


class TestPreLLMChecks:
    """Pre-LLM 检查测试"""

    @pytest.mark.asyncio
    async def test_tool_memory_check(self, pipeline, ctx, mock_agent):
        """应调用 tool_memory.check_tool_memory"""
        mock_agent.tool_memory = MagicMock()
        mock_agent.tool_memory.check_tool_memory = MagicMock(
            return_value=(None, "do_not_execute")
        )
        await pipeline._step_pre_llm_checks(ctx)
        mock_agent.tool_memory.check_tool_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_skill_acquisition_check(self, pipeline, ctx, mock_agent):
        """应调用 skill_manager.analyze_task"""
        mock_agent.skill_manager = MagicMock()
        mock_agent.skill_manager.auto_acquire = True
        mock_agent.skill_manager.analyze_task = MagicMock(return_value=None)
        await pipeline._step_pre_llm_checks(ctx)
        mock_agent.skill_manager.analyze_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_tool_memory(self, pipeline, ctx, mock_agent):
        """无 tool_memory 时应跳过检查"""
        mock_agent.tool_memory = None
        await pipeline._step_pre_llm_checks(ctx)
        # No exception should be raised

    @pytest.mark.asyncio
    async def test_no_skill_manager(self, pipeline, ctx, mock_agent):
        """无 skill_manager 时应跳过检查"""
        mock_agent.skill_manager = None
        await pipeline._step_pre_llm_checks(ctx)
        # No exception should be raised


class TestRetrieval:
    """检索测试"""

    @pytest.mark.skip(reason="旧 API unified_retriever.retrieve 已被 MemoryRetrievalChain 替代, "
                             "新 API 测试在 test_memory_retrieval_chain.py")
    @pytest.mark.asyncio
    async def test_unified_retriever(self, pipeline, ctx, mock_agent):
        """应使用 UnifiedRetriever 检索"""
        mock_agent.unified_retriever = MagicMock()
        mock_agent.unified_retriever.retrieve = MagicMock(return_value=[
            {"content": "test memory", "score": 0.9}
        ])
        await pipeline._retrieve_memories(ctx)
        assert len(ctx.relevant_memories) == 1
        mock_agent.unified_retriever.retrieve.assert_called_once()

    @pytest.mark.asyncio
    async def test_moe_fallback(self, pipeline, ctx, mock_agent):
        """无 UnifiedRetriever 时应 fallback 到 MoE"""
        mock_agent.unified_retriever = None
        mock_agent.memory_agent.moe_retrieve = MagicMock(return_value=[])
        await pipeline._retrieve_memories(ctx)
        mock_agent.memory_agent.moe_retrieve.assert_called_once()

    @pytest.mark.skip(reason="旧 API crystallizer.retrieve 已被 CrystallizedExperienceManager 替代, "
                             "新 API 测试在 test_crystallized_experience_manager.py")
    @pytest.mark.asyncio
    async def test_crystallized_patterns(self, pipeline, ctx, mock_agent):
        """应检索结晶经验"""
        mock_agent.crystallizer = MagicMock()
        mock_agent.crystallizer.retrieve = MagicMock(return_value=[
            {"pattern": "test", "confidence": 0.8}
        ])
        await pipeline._retrieve_crystallized_patterns(ctx)
        assert len(ctx.crystallized_patterns) == 1

    @pytest.mark.asyncio
    async def test_no_crystallizer(self, pipeline, ctx, mock_agent):
        """无结晶器时应跳过"""
        mock_agent.crystallizer = None
        await pipeline._retrieve_crystallized_patterns(ctx)
        assert ctx.crystallized_patterns == []


class TestContinueHint:
    """续写提示测试"""

    def test_chinese_hint(self, pipeline):
        """中文输入应生成中文提示"""
        hint = pipeline._build_continue_hint("你好世界", "你好，")
        assert "截断" in hint
        assert "接续" in hint

    def test_english_hint(self, pipeline):
        """英文输入应生成英文提示"""
        hint = pipeline._build_continue_hint("Hello world", "Hello,")
        assert "truncated" in hint
        assert "continue" in hint


class TestAPIConfigError:
    """API 配置错误检测测试"""

    def test_generic_exception(self):
        """普通异常不是 API 配置错误"""
        assert ChatPipeline._is_api_config_error(Exception("test")) is False

    def test_value_error(self):
        """ValueError 不是 API 配置错误"""
        assert ChatPipeline._is_api_config_error(ValueError("test")) is False
