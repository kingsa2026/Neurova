"""
TDD 红绿灯测试 — post_chat_pipeline + chat_pipeline 模块 11 个 bug 修复

测试文件路径: tests/unit/core/test_post_chat_pipeline_bugfix.py
被测源码:
  - neurova/post_chat_pipeline.py
  - neurova/agent/chat_pipeline.py

TDD 流程:
  1. 先写测试 (RED) — 确认 bug 存在
  2. 修复源码 (GREEN) — 确认测试通过
  3. 运行回归测试 — 确认零新回归

Bug 列表:
  #1 (HIGH)   _step_save_memory / _step_save_session 内部 except 吞掉编程错误
  #2 (HIGH)   memory_type="conversation" 无效枚举值 → 应为 "episodic"
  #3 (MEDIUM) save_memory=False 时仍写入 evolution
  #4 (MEDIUM) save_session 失败时 actual_session_id 回退为空字符串
  #5 (MEDIUM) chat_pipeline 未检查 post_chat_pipeline 是否为 None
  #6 (MEDIUM) PostChatPipeline 并发 _step_results 串扰
  #7 (LOW)    _save_emotion_to_memory 在 user_memory_id=None 时仍调用 set_emotion
  #8 (LOW)    _step_extract_conversation_rules dependency_graph 可能为 None
  #9 (LOW)    直接访问 evolution 私有属性 _tool_weights / _registered_tools
  #10 (LOW)   _step_save_memory save_memory 默认值为 True（应为 False）
  #11 (LOW)   chat_pipeline.py fallback 代码重复
"""

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
from neurova.post_chat_pipeline import PostChatPipeline, StepResult, StepStatus


# ============================================================
# 辅助 fixtures
# ============================================================


@pytest.fixture
def pipeline():
    """基础 PostChatPipeline 实例（无依赖注入）"""
    agent = MagicMock()
    agent._turn_count = 0
    agent._collect_tool_messages.return_value = []
    agent._save_to_session = MagicMock(return_value="test_session_id")
    agent._current_reasoning = None
    return PostChatPipeline(agent_ref=agent)


@pytest.fixture
def pipeline_with_memory(pipeline):
    """注入 memory_manager + conversation_buffer 的 pipeline"""
    memory_manager = MagicMock()
    memory_manager.remember = MagicMock(side_effect=["mem_user_1", "mem_agent_1"])
    emotion_module = MagicMock()
    emotion_module.analyze_text_emotion.return_value = None
    memory_manager.emotion_module = emotion_module

    conversation_buffer = MagicMock()

    pipeline.configure(
        memory_manager=memory_manager,
        conversation_buffer=conversation_buffer,
    )
    return pipeline


# ============================================================
# Bug #1 (HIGH) — _step_save_memory / _step_save_session 内部 except 吞掉编程错误
# ============================================================


class TestBug1ProgrammingErrorsNotSwallowed:
    """Bug #1: _step_save_memory 和 _step_save_session 内部 except 应 re-raise 编程错误"""

    @pytest.mark.asyncio
    async def test_step_save_memory_re_raises_type_error(self, pipeline_with_memory):
        """_step_save_memory 内部 TypeError 应 re-raise，不应降级为 FAILED"""
        # 让 memory_manager.remember 抛出 TypeError（编程错误）
        pipeline_with_memory._memory_manager.remember = MagicMock(
            side_effect=TypeError("wrong signature call")
        )

        with pytest.raises(TypeError, match="wrong signature call"):
            await pipeline_with_memory._step_save_memory(
                user_input="hello",
                reply="world",
                session_id="s1",
                save_memory=True,
            )

    @pytest.mark.asyncio
    async def test_step_save_memory_re_raises_attribute_error(self, pipeline_with_memory):
        """_step_save_memory 内部 AttributeError 应 re-raise"""
        pipeline_with_memory._memory_manager.remember = MagicMock(
            side_effect=AttributeError("no such attribute")
        )

        with pytest.raises(AttributeError, match="no such attribute"):
            await pipeline_with_memory._step_save_memory(
                user_input="hi", reply="hey", session_id="s1", save_memory=True
            )

    @pytest.mark.asyncio
    async def test_step_save_memory_re_raises_name_error(self, pipeline_with_memory):
        """_step_save_memory 内部 NameError 应 re-raise"""

        def raise_name_error(*args, **kwargs):
            raise NameError("undefined_var")

        pipeline_with_memory._memory_manager.remember = MagicMock(
            side_effect=raise_name_error
        )

        with pytest.raises(NameError):
            await pipeline_with_memory._step_save_memory(
                user_input="hi", reply="hey", session_id="s1", save_memory=True
            )

    @pytest.mark.asyncio
    async def test_step_save_session_re_raises_type_error(self, pipeline):
        """_step_save_session 内部 TypeError 应 re-raise"""
        # _save_to_session 抛出 TypeError
        pipeline._agt._save_to_session = MagicMock(side_effect=TypeError("type mismatch"))

        with pytest.raises(TypeError, match="type mismatch"):
            await pipeline._step_save_session(
                user_input="hello",
                reply="world",
                session_id="s1",
                save_memory=True,
                metadata={},
            )

    @pytest.mark.asyncio
    async def test_step_save_session_re_raises_attribute_error(self, pipeline):
        """_step_save_session 内部 AttributeError 应 re-raise"""
        pipeline._agt._save_to_session = MagicMock(
            side_effect=AttributeError("agent missing attr")
        )

        with pytest.raises(AttributeError, match="agent missing attr"):
            await pipeline._step_save_session(
                user_input="hello",
                reply="world",
                session_id="s1",
                save_memory=True,
                metadata={},
            )

    @pytest.mark.asyncio
    async def test_step_save_memory_still_degrades_operational_error(self, pipeline_with_memory):
        """运营错误（如 RuntimeError）仍应降级，不应 re-raise"""
        pipeline_with_memory._memory_manager.remember = MagicMock(
            side_effect=RuntimeError("db connection lost")
        )

        # 不应 raise，应降级为 FAILED
        await pipeline_with_memory._step_save_memory(
            user_input="hi", reply="hey", session_id="s1", save_memory=True
        )
        assert any(
            r.status == StepStatus.FAILED and "db connection lost" in r.message
            for r in pipeline_with_memory._step_results
        )


# ============================================================
# Bug #2 (HIGH) — memory_type="conversation" 无效枚举值
# ============================================================


class TestBug2MemoryTypeEpisodic:
    """Bug #2: memory_type 应为有效的 'episodic'，而非无效的 'conversation'"""

    @pytest.mark.asyncio
    async def test_memory_type_is_episodic(self, pipeline_with_memory):
        """保存用户记忆时 memory_type 应为 'episodic'（有效枚举值）"""
        captured_types = []
        original_remember = pipeline_with_memory._memory_manager.remember

        def capture_remember(*args, **kwargs):
            captured_types.append(kwargs.get("memory_type"))
            return original_remember(*args, **kwargs)

        pipeline_with_memory._memory_manager.remember = MagicMock(
            side_effect=capture_remember
        )

        await pipeline_with_memory._step_save_memory(
            user_input="hello", reply="world", session_id="s1", save_memory=True
        )

        # 应调用两次（用户 + 助手），都应为 "episodic"
        assert len(captured_types) == 2
        for mt in captured_types:
            assert mt == "episodic", f"memory_type 应为 'episodic'，实际为 '{mt}'"

    @pytest.mark.asyncio
    async def test_memory_type_not_conversation(self, pipeline_with_memory):
        """memory_type 不应为 'conversation'（无效枚举值）"""
        captured_types = []
        original_remember = pipeline_with_memory._memory_manager.remember

        def capture_remember(*args, **kwargs):
            captured_types.append(kwargs.get("memory_type"))
            return original_remember(*args, **kwargs)

        pipeline_with_memory._memory_manager.remember = MagicMock(
            side_effect=capture_remember
        )

        await pipeline_with_memory._step_save_memory(
            user_input="hi", reply="hey", session_id="s1", save_memory=True
        )

        for mt in captured_types:
            assert mt != "conversation", "memory_type 不应为无效值 'conversation'"


# ============================================================
# Bug #3 (MEDIUM) — save_memory=False 时仍写入 evolution
# ============================================================


class TestBug3SaveMemoryFalseSkipsEvolution:
    """Bug #3: save_memory=False 时应跳过 _step_record_experience 和 _step_p0_post_processing"""

    @pytest.mark.asyncio
    async def test_record_experience_skipped_when_save_memory_false(self, pipeline):
        """save_memory=False 时 _step_record_experience 应跳过，不调用 evolution"""
        evolution = MagicMock()
        evolution.on_experience_recorded = True
        pipeline.configure(evolution=evolution)

        await pipeline._step_record_experience(
            user_input="hi", reply="hey", save_memory=False
        )

        # 应记录 SKIPPED，不应调用 evolution
        skipped_results = [
            r for r in pipeline._step_results
            if r.step_name == "record_experience" and r.status == StepStatus.SKIPPED
        ]
        assert len(skipped_results) >= 1, "save_memory=False 时应跳过 record_experience"

    @pytest.mark.asyncio
    async def test_record_experience_runs_when_save_memory_true(self, pipeline):
        """save_memory=True 时 _step_record_experience 应正常执行"""
        evolution = MagicMock()
        evolution.on_experience_recorded = True
        # EvolutionFacade.record_experience 需要 facade
        pipeline.configure(evolution=evolution)

        await pipeline._step_record_experience(
            user_input="hi", reply="hey", save_memory=True
        )

        # 不应是 SKIPPED（可能 EXECUTED 或 FAILED，但不应该是因 save_memory=False 跳过）
        skipped_due_to_save_memory = [
            r for r in pipeline._step_results
            if r.step_name == "record_experience"
            and r.status == StepStatus.SKIPPED
            and "save_memory" in r.message.lower()
        ]
        assert len(skipped_due_to_save_memory) == 0

    @pytest.mark.asyncio
    async def test_p0_post_processing_skipped_when_save_memory_false(self, pipeline):
        """save_memory=False 时 _step_p0_post_processing 应跳过所有 P0 步骤"""
        tool_lifecycle = MagicMock()
        tool_lifecycle.evaluate = MagicMock(return_value={})
        pipeline.configure(tool_lifecycle=tool_lifecycle)

        await pipeline._step_p0_post_processing(save_memory=False)

        # 不应调用 tool_lifecycle.evaluate（因为 save_memory=False 应跳过）
        tool_lifecycle.evaluate.assert_not_called()

    @pytest.mark.asyncio
    async def test_p0_post_processing_runs_when_save_memory_true(self, pipeline):
        """save_memory=True 时 _step_p0_post_processing 应正常执行"""
        tool_lifecycle = MagicMock()
        tool_lifecycle.evaluate = MagicMock(return_value={})
        pipeline.configure(tool_lifecycle=tool_lifecycle)

        await pipeline._step_p0_post_processing(save_memory=True)

        # 应调用 tool_lifecycle.evaluate
        tool_lifecycle.evaluate.assert_called()


# ============================================================
# Bug #4 (MEDIUM) — actual_session_id 回退为空字符串
# ============================================================


class TestBug4SessionIdFallback:
    """Bug #4: save_session 失败时 actual_session_id 应回退到原始 session_id"""

    @pytest.mark.asyncio
    async def test_session_failure_preserves_none_session_id(self, pipeline):
        """save_session 失败且 session_id=None 时，actual_session_id 应为 None，而非空字符串

        Bug 根因: default=session_id or "" 会将 None 转为 ""
        修复后: default=session_id 保留原始 None
        """
        # 让 _save_to_session 抛出 RuntimeError（运营错误，被 _step_save_session 内部捕获）
        pipeline._agt._save_to_session = MagicMock(
            side_effect=RuntimeError("session save failed")
        )

        result = await pipeline.process(
            user_input="hello",
            reply="world",
            session_id=None,
            save_memory=True,
            enable_tts=False,
            metadata={},
        )

        # 修复前: actual_session_id = "" (via session_id or "")
        # 修复后: actual_session_id = None (原始 session_id)
        assert result["actual_session_id"] is None, (
            f"save_session 失败时应回退到原始 session_id (None)，实际为 '{result['actual_session_id']}'"
        )

    @pytest.mark.asyncio
    async def test_session_failure_does_not_convert_none_to_empty(self, pipeline):
        """session_id=None 时不应被 or "" 转为空字符串"""
        pipeline._agt._save_to_session = MagicMock(
            side_effect=RuntimeError("disk full")
        )

        result = await pipeline.process(
            user_input="hi",
            reply="hey",
            session_id=None,
            save_memory=True,
            enable_tts=False,
            metadata={},
        )

        # 不应为空字符串（None 被 or "" 转换的结果）
        assert result["actual_session_id"] != "", (
            "save_session 失败时 actual_session_id 不应将 None 转为空字符串"
        )
        assert result["actual_session_id"] is None


# ============================================================
# Bug #5 (MEDIUM) — chat_pipeline 未检查 post_chat_pipeline 是否为 None
# ============================================================


class TestBug5NonePostChatPipelineCheck:
    """Bug #5: post_chat_pipeline 为 None 时应抛出 RuntimeError，而非 AttributeError"""

    def _make_chat_pipeline_with_none_post_chat(self):
        """创建 post_chat_pipeline=None 的 ChatPipeline"""
        agent = MagicMock()
        agent.pipeline_executor = None  # 不走 PipelineExecutor 路径
        agent.post_chat_pipeline = None  # post_chat_pipeline 未初始化
        agent.memory_agent = MagicMock()
        agent.config = MagicMock()
        agent.crystallizer = None
        agent.unified_retriever = None
        agent._tool_messages_list = []
        agent._current_reasoning = None

        with patch.object(ChatPipeline, "_init_memory_retrieval_chain"):
            pipeline = ChatPipeline(agent_ref=agent)
        return pipeline, agent

    @pytest.mark.asyncio
    async def test_raises_runtime_error_when_post_chat_pipeline_is_none(self):
        """post_chat_pipeline=None 时应抛出 RuntimeError"""
        pipeline, agent = self._make_chat_pipeline_with_none_post_chat()

        ctx = ChatContext(
            user_input="hello",
            reply="world",
            session_id="s1",
            save_memory=True,
            enable_tts=False,
            metadata={},
        )
        ctx.caller_provided_history = True  # 跳过 history 更新

        with pytest.raises(RuntimeError, match="post_chat_pipeline"):
            await pipeline._step_post_processing(ctx)

    @pytest.mark.asyncio
    async def test_does_not_raise_attribute_error(self):
        """不应抛出 AttributeError（None.process() 的情况）"""
        pipeline, agent = self._make_chat_pipeline_with_none_post_chat()

        ctx = ChatContext(
            user_input="hello",
            reply="world",
            session_id="s1",
            save_memory=True,
            enable_tts=False,
            metadata={},
        )
        ctx.caller_provided_history = True

        # 应抛出 RuntimeError，不是 AttributeError
        with pytest.raises(RuntimeError):
            await pipeline._step_post_processing(ctx)


# ============================================================
# Bug #6 (MEDIUM) — PostChatPipeline 并发 _step_results 串扰
# ============================================================


class TestBug6StepResultsIsolation:
    """Bug #6: 并发 process() 调用应隔离 _step_results"""

    @pytest.mark.asyncio
    async def test_step_results_not_shared_between_sequential_calls(self, pipeline):
        """两次 process() 调用的 _step_results 应为不同列表对象"""
        pipeline._agt._save_to_session = MagicMock(return_value="s1")

        await pipeline.process(
            user_input="call1", reply="reply1", session_id="s1",
            save_memory=True, enable_tts=False, metadata={},
        )
        first_results = pipeline._step_results
        first_count = len(first_results)

        await pipeline.process(
            user_input="call2", reply="reply2", session_id="s2",
            save_memory=True, enable_tts=False, metadata={},
        )

        # 第一次调用的结果列表不应被第二次调用清空（不同对象）
        assert len(first_results) == first_count, (
            "第二次 process() 调用不应清空第一次调用的 _step_results（应隔离）"
        )

    @pytest.mark.asyncio
    async def test_concurrent_process_calls_do_not_mix_results(self, pipeline):
        """并发 process() 调用不应互相覆盖 _step_results"""
        # _save_to_session 被调用为 (user_input, reply, session_id, metadata, assistant_meta)
        # session_id 是第 3 个位置参数 (args[2])
        def mock_save(*args, **kwargs):
            return args[2] if len(args) > 2 else kwargs.get("session_id", "default")

        pipeline._agt._save_to_session = MagicMock(side_effect=mock_save)

        # 并发执行两个 process 调用
        results = await asyncio.gather(
            pipeline.process(
                user_input="input_a", reply="reply_a", session_id="session_a",
                save_memory=True, enable_tts=False, metadata={},
            ),
            pipeline.process(
                user_input="input_b", reply="reply_b", session_id="session_b",
                save_memory=True, enable_tts=False, metadata={},
            ),
        )

        # 两个调用都应成功完成，各自返回正确的 session_id
        assert results[0]["actual_session_id"] == "session_a"
        assert results[1]["actual_session_id"] == "session_b"


# ============================================================
# Bug #7 (LOW) — _save_emotion_to_memory 在 user_memory_id=None 时仍调用 set_emotion
# ============================================================


class TestBug7EmotionMemoryNoneCheck:
    """Bug #7: user_memory_id=None 时不应调用 set_emotion"""

    def test_no_set_emotion_when_memory_id_is_none(self, pipeline):
        """memory_id=None 时不应调用 emotion_module.set_emotion"""
        memory_manager = MagicMock()
        emotion_module = MagicMock()
        emotion_state = MagicMock()
        emotion_state.primary_emotion.value = "happy"
        emotion_module.analyze_text_emotion.return_value = emotion_state
        memory_manager.emotion_module = emotion_module

        pipeline._save_emotion_to_memory(memory_manager, "hello", memory_id=None)

        emotion_module.set_emotion.assert_not_called()

    def test_no_set_emotion_when_memory_id_is_empty(self, pipeline):
        """memory_id='' 时不应调用 emotion_module.set_emotion"""
        memory_manager = MagicMock()
        emotion_module = MagicMock()
        emotion_state = MagicMock()
        emotion_state.primary_emotion.value = "happy"
        emotion_module.analyze_text_emotion.return_value = emotion_state
        memory_manager.emotion_module = emotion_module

        pipeline._save_emotion_to_memory(memory_manager, "hello", memory_id="")

        emotion_module.set_emotion.assert_not_called()

    def test_set_emotion_called_when_memory_id_present(self, pipeline):
        """memory_id 有值时应正常调用 set_emotion"""
        memory_manager = MagicMock()
        emotion_module = MagicMock()
        emotion_state = MagicMock()
        emotion_state.primary_emotion.value = "happy"
        emotion_module.analyze_text_emotion.return_value = emotion_state
        memory_manager.emotion_module = emotion_module

        pipeline._save_emotion_to_memory(memory_manager, "hello", memory_id="mem_123")

        emotion_module.set_emotion.assert_called_once_with("mem_123", emotion_state)


# ============================================================
# Bug #8 (LOW) — dependency_graph 可能为 None
# ============================================================


class TestBug8DependencyGraphNoneCheck:
    """Bug #8: dependency_graph=None 时 _step_extract_conversation_rules 应跳过"""

    @pytest.mark.asyncio
    async def test_skips_when_dependency_graph_is_none(self, pipeline):
        """dependency_graph=None 且 rule_extractor=None 时应跳过，不应崩溃"""
        # 显式设为 None 防止 MagicMock 自动创建属性返回 MagicMock 而非 None
        pipeline._agt.dependency_graph = None
        pipeline._agt.rule_extractor = None
        pipeline._agt.llm_client = None
        await pipeline._step_extract_conversation_rules(
            user_input="hi", reply="hey", session_id="s1"
        )

        skipped = [
            r for r in pipeline._step_results
            if r.step_name == "extract_conversation_rules" and r.status == StepStatus.SKIPPED
        ]
        assert len(skipped) >= 1, "dependency_graph=None 时应跳过"

    @pytest.mark.asyncio
    async def test_skips_when_dependency_graph_none_but_llm_available(self, pipeline):
        """有 llm_client 但 dependency_graph=None 时也应跳过（不应传 None 给构造器）"""
        # 显式设置：llm_client 可用，dependency_graph=None
        pipeline._agt.llm_client = MagicMock()
        pipeline._agt.dependency_graph = None
        pipeline._agt.rule_extractor = None

        await pipeline._step_extract_conversation_rules(
            user_input="hi", reply="hey", session_id="s1"
        )

        # 不应崩溃，应优雅跳过
        all_results = [
            r for r in pipeline._step_results
            if r.step_name == "extract_conversation_rules"
        ]
        assert len(all_results) >= 1
        # 应该是 SKIPPED（dependency_graph=None 时不应传给构造器）
        skipped = [
            r for r in all_results if r.status == StepStatus.SKIPPED
        ]
        assert len(skipped) >= 1, "有 llm 但 dependency_graph=None 时应跳过"


# ============================================================
# Bug #9 (LOW) — 直接访问 evolution 私有属性
# ============================================================


class TestBug9NoPrivateAttributeAccess:
    """Bug #9: 不应直接访问 evolution._tool_weights / evolution._registered_tools"""

    @pytest.mark.asyncio
    async def test_lifecycle_evaluate_uses_public_tool_weights(self, pipeline):
        """_step_lifecycle_evaluate 应使用 evolution.tool_weights（公开），而非 _tool_weights"""
        tool_lifecycle = MagicMock()
        tool_lifecycle.evaluate = MagicMock(return_value={
            "decay": {"tool_a": 0.5, "tool_b": 0.8},
        })

        # 创建 evolution mock：有公开 tool_weights，无私有 _tool_weights
        evolution = MagicMock()
        evolution._tool_weights = None  # 明确没有私有属性
        tool_weights = MagicMock()
        tool_weights.get_tool_entry = MagicMock(return_value=MagicMock())  # 工具存在
        tool_weights.record_failure = MagicMock()
        evolution.tool_weights = tool_weights

        pipeline.configure(tool_lifecycle=tool_lifecycle, evolution=evolution)

        await pipeline._step_lifecycle_evaluate()

        # 应调用公开的 tool_weights 方法，不应访问私有 _tool_weights
        # 验证 record_failure 被调用（而非直接修改 _tool_weights）
        assert tool_weights.record_failure.called, (
            "应通过 tool_weights.record_failure() 公开方法操作，而非直接访问 _tool_weights"
        )

    @pytest.mark.asyncio
    async def test_genetic_evolution_uses_public_api(self, pipeline):
        """_step_genetic_evolution 应使用公开方法检查工具注册，而非 _registered_tools"""
        from neurova.evolution.genetic_engine import ToolGenotype

        pattern_miner = MagicMock()
        pattern_miner.sequence_count = 1
        pattern_miner.get_top_patterns.return_value = [
            MagicMock(tools=["tool_x", "tool_y"]),
        ]

        genetic_engine = MagicMock()
        genetic_engine.population = []
        genetic_engine.evolve.return_value = [
            ToolGenotype(tool_sequence=["tool_x"], success_rate=0.8),
        ]
        genetic_engine.register_to_skill_registry.return_value = 0

        evolution = MagicMock()
        evolution._registered_tools = None  # 无私有属性
        tool_weights = MagicMock()
        tool_weights.get_tool_entry = MagicMock(return_value=MagicMock())  # 工具存在
        tool_weights.update_weight = MagicMock()
        evolution.tool_weights = tool_weights
        # _step_genetic_evolution 从 evolution 对象获取 genetic_engine/pattern_miner
        evolution.genetic_engine = genetic_engine
        evolution.pattern_miner = pattern_miner

        pipeline.configure(
            pattern_miner=pattern_miner,
            genetic_engine=genetic_engine,
            evolution=evolution,
        )
        pipeline._agt._skill_registry = None

        await pipeline._step_genetic_evolution()

        # 应通过公开 API 检查工具存在，而非访问 _registered_tools
        # 验证 update_weight 被调用（公开方法）
        assert tool_weights.update_weight.called or tool_weights.get_tool_entry.called, (
            "应通过 tool_weights 公开方法操作，而非直接访问 _registered_tools"
        )


# ============================================================
# Bug #10 (LOW) — _step_save_memory save_memory 默认值为 True
# ============================================================


class TestBug10SaveMemoryDefaultFalse:
    """Bug #10: _step_save_memory 的 save_memory 默认值应为 False"""

    def test_save_memory_default_is_false(self):
        """_step_save_memory 的 save_memory 参数默认值应为 False"""
        sig = inspect.signature(PostChatPipeline._step_save_memory)
        save_memory_param = sig.parameters.get("save_memory")

        assert save_memory_param is not None, "save_memory 参数应存在"
        assert save_memory_param.default is False, (
            f"save_memory 默认值应为 False，实际为 {save_memory_param.default}"
        )

    def test_save_memory_default_not_true(self):
        """save_memory 默认值不应为 True（避免意外写入记忆）"""
        sig = inspect.signature(PostChatPipeline._step_save_memory)
        save_memory_param = sig.parameters.get("save_memory")

        assert save_memory_param.default is not True, (
            "save_memory 默认值不应为 True（应为 False 以避免意外写入）"
        )


# ============================================================
# Bug #11 (LOW) — chat_pipeline.py fallback 代码重复
# ============================================================


class TestBug11ExtractFallbackHelper:
    """Bug #11: 应提取 _run_post_chat_pipeline 辅助方法消除重复"""

    def test_run_post_chat_pipeline_method_exists(self):
        """ChatPipeline 应有 _run_post_chat_pipeline 辅助方法"""
        assert hasattr(ChatPipeline, "_run_post_chat_pipeline"), (
            "ChatPipeline 应提取 _run_post_chat_pipeline 辅助方法消除 fallback 代码重复"
        )

    def test_run_post_chat_pipeline_is_coroutine(self):
        """_run_post_chat_pipeline 应为 async 方法"""
        assert hasattr(ChatPipeline, "_run_post_chat_pipeline")
        method = getattr(ChatPipeline, "_run_post_chat_pipeline")
        assert asyncio.iscoroutinefunction(method), (
            "_run_post_chat_pipeline 应为 async 方法"
        )

    @pytest.mark.asyncio
    async def test_run_post_chat_pipeline_checks_none(self):
        """_run_post_chat_pipeline 应检查 post_chat_pipeline 是否为 None"""
        agent = MagicMock()
        agent.pipeline_executor = None
        agent.post_chat_pipeline = None
        agent.memory_agent = MagicMock()
        agent.config = MagicMock()
        agent.crystallizer = None
        agent.unified_retriever = None
        agent._tool_messages_list = []

        with patch.object(ChatPipeline, "_init_memory_retrieval_chain"):
            pipeline = ChatPipeline(agent_ref=agent)

        ctx = ChatContext(
            user_input="hello", reply="world", session_id="s1",
            save_memory=True, enable_tts=False, metadata={},
        )

        with pytest.raises(RuntimeError, match="post_chat_pipeline"):
            await pipeline._run_post_chat_pipeline(ctx)

    @pytest.mark.asyncio
    async def test_run_post_chat_pipeline_calls_process(self):
        """_run_post_chat_pipeline 应调用 post_chat_pipeline.process()"""
        agent = MagicMock()
        agent.pipeline_executor = None
        mock_post_chat = MagicMock()
        mock_post_chat.process = AsyncMock(return_value={
            "actual_session_id": "s1",
            "audio_path": None,
            "audio_data": None,
            "cognitive_score": 0.5,
            "proactive_question": None,
        })
        agent.post_chat_pipeline = mock_post_chat
        agent.memory_agent = MagicMock()
        agent.config = MagicMock()
        agent.crystallizer = None
        agent.unified_retriever = None
        agent._tool_messages_list = []

        with patch.object(ChatPipeline, "_init_memory_retrieval_chain"):
            pipeline = ChatPipeline(agent_ref=agent)

        ctx = ChatContext(
            user_input="hello", reply="world", session_id="s1",
            save_memory=True, enable_tts=False, metadata={},
        )

        result = await pipeline._run_post_chat_pipeline(ctx)
        mock_post_chat.process.assert_called_once()
        assert result["actual_session_id"] == "s1"
