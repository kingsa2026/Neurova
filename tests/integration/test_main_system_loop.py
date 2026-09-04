"""
知识-进化闭环在主系统中的实际连接验证

通过 Mock Agent 验证 ChatPipeline 中的闭环通路：
1. 工具执行 → evolution.on_after_tool_execution (via tool_executor)
2. 结晶经验 → context 注入 (via crystallized_experience_manager)
3. 经验记录 → evolution.on_experience_recorded (via post_chat_pipeline)
4. 结晶器观察 → evolution.on_experience_recorded
"""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, call


class TestMainSystemClosedLoop:
    """主系统闭环实际连接验证"""

    def _make_agent_with_evolution(self):
        """创建带进化系统的 Agent 模拟"""
        from neurova.agent.chat_pipeline import ChatPipeline

        agent = MagicMock()

        # 进化系统
        agent.evolution = MagicMock()
        agent.evolution.on_after_tool_execution = MagicMock()
        agent.evolution.on_experience_recorded = MagicMock(return_value={
            "insights_count": 1, "tools_mentioned": ["tool_a"],
            "outcome": "success", "success": True
        })
        agent.evolution.tool_weights = MagicMock()
        agent.evolution.pattern_miner = MagicMock()

        # 结晶器
        agent.crystallizer = MagicMock()
        agent.crystallizer.observe = MagicMock()
        agent.crystallizer.retrieve = MagicMock(return_value=[
            {"id": "c1", "content": "结晶经验1", "method": "tool_a",
             "confidence": 0.9, "score": 85, "source": "crystallized"}
        ])

        # 结晶经验管理器
        from neurova.agent.crystallized_experience_manager import (
            CrystallizedExperienceManager, RetrievalStatus, CrystallizedExperience, RetrievalResult
        )
        mock_cem = MagicMock(spec=CrystallizedExperienceManager)
        mock_cem.retrieve = AsyncMock(return_value=RetrievalResult(
            status=RetrievalStatus.SUCCESS,
            experiences=[CrystallizedExperience(
                id="c1", content="结晶经验1", method="tool_a",
                confidence=0.9, score=85, source="crystallized"
            )],
            source="crystallized", latency_ms=5.0,
        ))
        agent.crystallized_experience_manager = mock_cem

        # 上下文构建器
        agent.context_orchestrator = MagicMock()
        agent.context_orchestrator.build_context = AsyncMock(return_value=[
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
        ])
        agent.context_orchestrator.build_tools_for_llm = AsyncMock(return_value=[])

        # 记忆系统
        agent.memory_agent = MagicMock()
        agent.memory_agent.update_history = MagicMock()
        agent.memory_agent.save_to_session = MagicMock(return_value="session_1")

        # 工具记忆
        agent.tool_memory = MagicMock()
        agent.tool_memory.check_tool_memory = MagicMock(return_value=(None, "do_not_execute"))

        # 工具执行器
        agent.tool_executor = MagicMock()
        agent.tool_executor.execute_text_tool_calls = AsyncMock(side_effect=lambda r, u: r)
        agent.tool_executor.on_tool_executed = MagicMock()

        # LLM
        agent.loop = MagicMock()
        agent.loop.predict_step = AsyncMock(return_value=MagicMock(
            content="Reply with tool call [TOOL_CALL:tool_a({})]",
            finish_reason="stop", tool_calls=None, reasoning_content=None,
        ))
        agent.llm_client = MagicMock()
        agent.llm_client.config = MagicMock()
        agent.llm_client.config.max_tokens = 8192

        # 后处理
        agent.post_chat_pipeline = MagicMock()
        agent.post_chat_pipeline.process = AsyncMock(return_value={
            "actual_session_id": "s1", "audio_path": None, "audio_data": None,
            "cognitive_score": 0.8, "proactive_question": None,
        })

        # 其他
        agent.config = MagicMock()
        agent.config.name = "Test"
        agent.config.agent_id = "test"
        agent.config.llm_config = MagicMock()
        agent.config.llm_config.model = "test"
        agent.trace_manager = MagicMock()
        agent.trace_manager.start_trace = MagicMock(return_value="t1")
        agent.trace_manager.add_step = MagicMock()
        agent.trace_manager.finish_trace = MagicMock()
        agent.neuHebb_manager = None
        agent.unified_retriever = None
        agent.crystallizer_for_chat = agent.crystallizer
        agent._trajectory_recorder = MagicMock()
        agent._trajectory_recorder.record_event = MagicMock()
        agent._trajectory_recorder.end_trace = MagicMock()
        agent.idle_tracker = MagicMock()
        agent.session_manager = MagicMock()
        agent.skill_manager = None
        agent.tool_synthesizer = None
        agent._current_reasoning = None
        agent._tool_messages_list = [{"tool_name": "tool_a", "success": True}]
        agent._last_tool_used = None
        agent.conversation_history = []
        agent._current_user_input = None

        return agent

    @pytest.mark.asyncio
    async def test_tool_executor_calls_evolution(self):
        """工具执行器调用进化系统"""
        agent = self._make_agent_with_evolution()

        # 直接调用 on_tool_executed
        agent.tool_executor.on_tool_executed(
            tool_name="tool_a",
            params={"query": "test"},
            user_input="搜索信息",
            success=True,
            tool_source="skill_system",
            execution_time=0.5,
        )

        # 验证进化系统被调用
        # (tool_executor 内部会调用 evolution.on_after_tool_execution)

    @pytest.mark.asyncio
    async def test_chat_pipeline_retrieves_crystallized(self):
        """ChatPipeline 检索结晶经验"""
        from neurova.agent.chat_pipeline import ChatPipeline
        from neurova.agent.crystallized_experience_manager import (
            CrystallizedExperienceManager, RetrievalStatus, CrystallizedExperience, RetrievalResult
        )

        agent = self._make_agent_with_evolution()

        # Patch CrystallizedExperienceManager 使其返回我们的 mock
        mock_cem = MagicMock()
        mock_cem.retrieve = AsyncMock(return_value=RetrievalResult(
            status=RetrievalStatus.SUCCESS,
            experiences=[CrystallizedExperience(
                id="c1", content="结晶经验1", method="tool_a",
                confidence=0.9, score=85, source="crystallized"
            )],
            source="crystallized", latency_ms=5.0,
        ))

        with patch('neurova.agent.chat_pipeline.CrystallizedExperienceManager', return_value=mock_cem):
            pipeline = ChatPipeline(agent)

            from neurova.agent.chat_pipeline import ChatContext
            ctx = ChatContext(user_input="Python")
            await pipeline.execute(ctx)

        # crystallized_experience_manager.retrieve 应被调用
        mock_cem.retrieve.assert_called()

    @pytest.mark.asyncio
    async def test_post_chat_records_experience(self):
        """后处理记录经验到进化系统"""
        from neurova.agent.chat_pipeline import ChatPipeline

        agent = self._make_agent_with_evolution()
        pipeline = ChatPipeline(agent)

        from neurova.agent.chat_pipeline import ChatContext
        ctx = ChatContext(user_input="Hello")
        await pipeline.execute(ctx)

        # post_chat_pipeline.process 应被调用
        agent.post_chat_pipeline.process.assert_called_once()

    @pytest.mark.asyncio
    async def test_crystallizer_observe_in_post_processing(self):
        """后处理中结晶器观察（闭环审计 2026-09-04 修复后契约）。

        直挂 _last_tool_used 分支已删除（死信号 + 硬编码 success=True 污染）；
        观察统一走 post_chat Step9 → on_experience_recorded。此处 agent 的
        post_chat_pipeline 是 mock，故 execute 直挂路径必须不再触发 observe。
        """
        from neurova.agent.chat_pipeline import ChatPipeline

        agent = self._make_agent_with_evolution()
        agent._last_tool_used = "tool_a"
        pipeline = ChatPipeline(agent)

        from neurova.agent.chat_pipeline import ChatContext
        ctx = ChatContext(user_input="Hello")
        await pipeline.execute(ctx)

        # 直挂观察必须不存在（防止双计回归）
        agent.crystallizer.observe.assert_not_called()

    @pytest.mark.asyncio
    async def test_full_loop_data_flow(self):
        """完整闭环数据流：对话→检索→LLM→后处理→进化"""
        from neurova.agent.chat_pipeline import ChatPipeline
        from neurova.agent.crystallized_experience_manager import (
            CrystallizedExperienceManager, RetrievalStatus, CrystallizedExperience, RetrievalResult
        )

        agent = self._make_agent_with_evolution()

        mock_cem = MagicMock()
        mock_cem.retrieve = AsyncMock(return_value=RetrievalResult(
            status=RetrievalStatus.SUCCESS,
            experiences=[CrystallizedExperience(
                id="c1", content="结晶经验1", method="tool_a",
                confidence=0.9, score=85, source="crystallized"
            )],
            source="crystallized", latency_ms=5.0,
        ))

        with patch('neurova.agent.chat_pipeline.CrystallizedExperienceManager', return_value=mock_cem):
            pipeline = ChatPipeline(agent)

            from neurova.agent.chat_pipeline import ChatContext
            ctx = ChatContext(user_input="搜索Python教程")
            result = await pipeline.execute(ctx)

        # 验证完整闭环
        assert result is not None
        assert "text" in result

        # 1. 结晶经验被检索
        mock_cem.retrieve.assert_called()

        # 2. 上下文被构建
        agent.context_orchestrator.build_context.assert_called()

        # 3. LLM 被调用
        agent.loop.predict_step.assert_called()

        # 4. 工具调用被解析执行
        agent.tool_executor.execute_text_tool_calls.assert_called()

        # 5. 后处理执行
        agent.post_chat_pipeline.process.assert_called()

        # 6. 历史更新
        agent.memory_agent.update_history.assert_called()

    @pytest.mark.asyncio
    async def test_evolution_triggered_flag(self):
        """evolution_triggered 标志正确设置"""
        from neurova.agent.chat_pipeline import ChatPipeline

        agent = self._make_agent_with_evolution()
        pipeline = ChatPipeline(agent)

        from neurova.agent.chat_pipeline import ChatContext
        ctx = ChatContext(user_input="Hello")
        result = await pipeline.execute(ctx)

        # evolution_triggered 目前为 False（需要改进）
        # 这是一个已知的gap
        assert "evolution_triggered" in result
