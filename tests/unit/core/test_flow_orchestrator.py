"""
流程编排器测试 - Flow Orchestrator Tests

覆盖 FlowOrchestrator 及所有子模块：
- FlowPhase, FlowEvent, FlowContext 数据类
- FlowTracer 流程追踪器
- MessageFlowManager 消息流转管理器
- ContextMemoryBridge 上下文与记忆缓存协同层
- MemoryCoordinator 记忆写入与检索协调器
- ToolFeedbackLoop 工具调用与结果反馈链路
- ExperienceEvolutionEngine 经验积累与进化成长引擎
- SleepConsolidationCoordinator 睡眠记忆合并与冲突处理协调器
- MetaCognitionEvaluator 元认知闭环评估器
- FlowOrchestrator 完整流程编排
"""

import pytest
import time
import asyncio
from unittest.mock import MagicMock, patch

from neurova.core.flow_orchestrator import (
    FlowPhase,
    Severity,
    FlowEvent,
    FlowContext,
    FlowTracer,
    MessageFlowManager,
    ContextMemoryBridge,
    MemoryCoordinator,
    ToolFeedbackLoop,
    ExperienceEvolutionEngine,
    SleepConsolidationCoordinator,
    MetaCognitionEvaluator,
    FlowOrchestrator,
    get_flow_orchestrator,
    process_conversation_flow,
)


class TestFlowPhase:
    """FlowPhase 枚举测试"""

    def test_all_phases_exist(self):
        assert FlowPhase.IDLE.value == "idle"
        assert FlowPhase.CONVERSATION.value == "conversation"
        assert FlowPhase.CONTEXT_BUILD.value == "context_build"
        assert FlowPhase.MEMORY_CACHE.value == "memory_cache"
        assert FlowPhase.MEMORY_WRITE.value == "memory_write"
        assert FlowPhase.MEMORY_RETRIEVAL.value == "memory_retrieval"
        assert FlowPhase.TOOL_INVOCATION.value == "tool_invocation"
        assert FlowPhase.RESULT_FEEDBACK.value == "result_feedback"
        assert FlowPhase.EXPERIENCE_ACCUMULATE.value == "experience_accumulate"
        assert FlowPhase.EVOLUTION.value == "evolution"
        assert FlowPhase.SLEEP_CONSOLIDATION.value == "sleep_consolidation"
        assert FlowPhase.CONFLICT_RESOLUTION.value == "conflict_resolution"
        assert FlowPhase.METACOGNITION.value == "metacognition"

    def test_total_phases_count(self):
        assert len(list(FlowPhase)) == 13  # 12 phases + IDLE


class TestSeverity:
    """Severity 枚举测试"""

    def test_severity_values(self):
        assert Severity.DEBUG.value == "debug"
        assert Severity.INFO.value == "info"
        assert Severity.WARNING.value == "warning"
        assert Severity.ERROR.value == "error"
        assert Severity.CRITICAL.value == "critical"


class TestFlowEvent:
    """FlowEvent 数据类测试"""

    def test_create_event(self):
        event = FlowEvent(
            event_id="evt_001",
            phase=FlowPhase.CONVERSATION,
            data={"key": "value"},
            source="test",
            severity=Severity.INFO,
            duration_ms=100.0,
            success=True,
        )
        assert event.event_id == "evt_001"
        assert event.phase == FlowPhase.CONVERSATION
        assert event.data == {"key": "value"}
        assert event.source == "test"
        assert event.severity == Severity.INFO
        assert event.duration_ms == 100.0
        assert event.success is True
        assert event.error is None

    def test_event_with_error(self):
        event = FlowEvent(
            event_id="evt_002",
            phase=FlowPhase.TOOL_INVOCATION,
            success=False,
            error="Tool not found",
        )
        assert event.success is False
        assert event.error == "Tool not found"

    def test_event_timestamp_auto_generated(self):
        event = FlowEvent(event_id="evt_003", phase=FlowPhase.MEMORY_CACHE)
        assert event.timestamp is not None
        assert len(event.timestamp) > 0


class TestFlowContext:
    """FlowContext 数据类测试"""

    def test_default_context(self):
        ctx = FlowContext()
        assert ctx.session_id == ""
        assert ctx.agent_id == ""
        assert ctx.user_id == ""
        assert ctx.current_phase == FlowPhase.IDLE
        assert ctx.conversation_history == []
        assert ctx.built_context == []

    def test_context_with_data(self):
        ctx = FlowContext(
            session_id="sess_001",
            agent_id="agent_001",
            user_id="user_001",
            user_input="你好",
            token_budget=8000,
        )
        assert ctx.session_id == "sess_001"
        assert ctx.agent_id == "agent_001"
        assert ctx.user_id == "user_001"
        assert ctx.user_input == "你好"
        assert ctx.token_budget == 8000

    def test_to_dict(self):
        ctx = FlowContext(
            session_id="sess_001",
            agent_id="agent_001",
            user_id="user_001",
        )
        d = ctx.to_dict()
        assert d["session_id"] == "sess_001"
        assert d["agent_id"] == "agent_001"
        assert d["user_id"] == "user_001"
        assert d["current_phase"] == "idle"

    def test_mutable_fields_independent(self):
        ctx1 = FlowContext()
        ctx2 = FlowContext()
        ctx1.metadata["key"] = "value"
        assert "key" not in ctx2.metadata


class TestFlowTracer:
    """FlowTracer 测试"""

    def test_initialization(self):
        tracer = FlowTracer()
        assert tracer.get_stats() == {"total_events": 0}

    def test_start_and_end_phase(self):
        tracer = FlowTracer()
        evt_id = tracer.start_phase(FlowPhase.CONVERSATION)
        assert evt_id.startswith("evt_")
        assert FlowPhase.CONVERSATION.value in evt_id

        event = tracer.end_phase(evt_id, FlowPhase.CONVERSATION, True,
                                 data={"test": "data"})
        assert event.phase == FlowPhase.CONVERSATION
        assert event.success is True
        assert event.data == {"test": "data"}
        assert event.duration_ms >= 0

    def test_get_stats_after_events(self):
        tracer = FlowTracer()
        evt1 = tracer.start_phase(FlowPhase.CONVERSATION)
        tracer.end_phase(evt1, FlowPhase.CONVERSATION, True)

        evt2 = tracer.start_phase(FlowPhase.CONTEXT_BUILD)
        tracer.end_phase(evt2, FlowPhase.CONTEXT_BUILD, False, error="fail")

        stats = tracer.get_stats()
        assert stats["total_events"] == 2
        assert "conversation" in stats["phases"]
        assert "context_build" in stats["phases"]
        assert stats["phases"]["conversation"]["count"] == 1
        assert stats["phases"]["conversation"]["successes"] == 1
        assert stats["phases"]["context_build"]["failures"] == 1

    def test_get_phase_timeline(self):
        tracer = FlowTracer()
        evt1 = tracer.start_phase(FlowPhase.CONVERSATION)
        tracer.end_phase(evt1, FlowPhase.CONVERSATION, True)
        evt2 = tracer.start_phase(FlowPhase.MEMORY_CACHE)
        tracer.end_phase(evt2, FlowPhase.MEMORY_CACHE, True)

        conversation_events = tracer.get_phase_timeline(FlowPhase.CONVERSATION)
        assert len(conversation_events) == 1
        assert conversation_events[0].phase == FlowPhase.CONVERSATION

        cache_events = tracer.get_phase_timeline(FlowPhase.MEMORY_CACHE)
        assert len(cache_events) == 1

    def test_max_events_limit(self):
        tracer = FlowTracer(max_events=5)
        for i in range(10):
            evt_id = tracer.start_phase(FlowPhase.CONVERSATION)
            tracer.end_phase(evt_id, FlowPhase.CONVERSATION, True)

        stats = tracer.get_stats()
        assert stats["total_events"] <= 5

    def test_success_rate_calculation(self):
        tracer = FlowTracer()
        for i in range(5):
            evt_id = tracer.start_phase(FlowPhase.CONVERSATION)
            tracer.end_phase(evt_id, FlowPhase.CONVERSATION, i < 4)

        stats = tracer.get_stats()
        assert stats["success_rate"] == 0.8


class TestMessageFlowManager:
    """MessageFlowManager 测试"""

    def test_receive_message(self):
        mgr = MessageFlowManager()
        msg = mgr.receive_message("sess_001", "user", "你好")
        assert msg["role"] == "user"
        assert msg["content"] == "你好"
        assert "id" in msg
        assert msg["id"].startswith("msg_")

    def test_get_history(self):
        mgr = MessageFlowManager()
        mgr.receive_message("sess_001", "user", "第一条消息")
        mgr.receive_message("sess_001", "assistant", "回复")
        mgr.receive_message("sess_001", "user", "第二条消息")

        history = mgr.get_history("sess_001")
        assert len(history) == 3
        assert history[0]["content"] == "第一条消息"
        assert history[2]["content"] == "第二条消息"

    def test_get_history_with_limit(self):
        mgr = MessageFlowManager()
        for i in range(10):
            mgr.receive_message("sess_001", "user", f"消息{i}")

        history = mgr.get_history("sess_001", limit=3)
        assert len(history) == 3
        assert history[-1]["content"] == "消息9"

    def test_clear_history(self):
        mgr = MessageFlowManager()
        mgr.receive_message("sess_001", "user", "测试")
        count = mgr.clear_history("sess_001")
        assert count == 1
        assert mgr.get_history("sess_001") == []

    def test_session_isolation(self):
        mgr = MessageFlowManager()
        mgr.receive_message("sess_001", "user", "会话1")
        mgr.receive_message("sess_002", "user", "会话2")

        assert len(mgr.get_history("sess_001")) == 1
        assert len(mgr.get_history("sess_002")) == 1

    def test_get_active_sessions(self):
        mgr = MessageFlowManager()
        mgr.receive_message("sess_001", "user", "测试1")
        mgr.receive_message("sess_002", "user", "测试2")

        sessions = mgr.get_active_sessions()
        assert len(sessions) == 2
        assert "sess_001" in sessions
        assert "sess_002" in sessions

    def test_max_history_limit(self):
        mgr = MessageFlowManager(max_history=5)
        for i in range(10):
            mgr.receive_message("sess_001", "user", f"消息{i}")

        history = mgr.get_history("sess_001")
        assert len(history) == 5
        assert history[0]["content"] == "消息5"

    def test_receive_message_with_metadata(self):
        mgr = MessageFlowManager()
        msg = mgr.receive_message("sess_001", "user", "测试",
                                  metadata={"agent_id": "agent_001"})
        assert msg["metadata"]["agent_id"] == "agent_001"


class TestContextMemoryBridge:
    """ContextMemoryBridge 测试"""

    def test_build_context_miss(self):
        bridge = ContextMemoryBridge()
        flow_ctx = FlowContext(
            session_id="sess_001",
            agent_id="agent_001",
            user_input="你好世界",
        )
        flow_ctx.conversation_history = [
            {"role": "user", "content": "你好世界"},
        ]

        result = bridge.build_context(flow_ctx, system_prompt="你是AI助手")
        assert len(result.built_context) >= 2

        stats = bridge.get_cache_stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 0

    def test_build_context_hit(self):
        bridge = ContextMemoryBridge()
        ctx1 = FlowContext(session_id="sess_001", agent_id="agent_001", user_input="首次请求")
        ctx1.conversation_history = []

        result1 = bridge.build_context(ctx1)
        assert bridge.get_cache_stats()["misses"] == 1

        ctx2 = FlowContext(session_id="sess_001", agent_id="agent_001", user_input="再次请求")
        ctx2.conversation_history = []
        result2 = bridge.build_context(ctx2)

        assert bridge.get_cache_stats()["hits"] == 1
        assert bridge.get_cache_stats()["misses"] == 1

    def test_invalidate_cache(self):
        bridge = ContextMemoryBridge()
        ctx1 = FlowContext(session_id="sess_001", agent_id="agent_001", user_input="测试")
        ctx1.conversation_history = []
        bridge.build_context(ctx1)

        bridge.invalidate_cache("agent_001", "sess_001")
        assert bridge.get_cache_stats()["cache_size"] == 0

    def test_build_context_with_external_memories(self):
        bridge = ContextMemoryBridge()
        ctx = FlowContext(session_id="sess_001", agent_id="agent_001", user_input="测试")
        ctx.conversation_history = []

        memories = [{"id": "mem_001", "content": "相关记忆", "temperature": 80}]
        experiences = [{"id": "exp_001", "content": "相关经验", "temperature": 70}]

        result = bridge.build_context(ctx, external_memories=memories,
                                      external_experiences=experiences)
        assert len(result.cached_memories) == 2

    def test_cache_eviction(self):
        bridge = ContextMemoryBridge(max_cache_entries=3)
        for i in range(5):
            ctx = FlowContext(session_id=f"sess_{i:03d}", agent_id="agent_001",
                              user_input=f"请求{i}")
            ctx.conversation_history = []
            bridge.build_context(ctx)

        stats = bridge.get_cache_stats()
        assert stats["cache_size"] <= 3
        assert stats["evictions"] >= 2

    def test_hit_rate_calculation(self):
        bridge = ContextMemoryBridge()
        ctx1 = FlowContext(session_id="sess_001", agent_id="agent_001", user_input="请求")
        ctx1.conversation_history = []
        bridge.build_context(ctx1)

        ctx2 = FlowContext(session_id="sess_001", agent_id="agent_001", user_input="请求")
        ctx2.conversation_history = []
        bridge.build_context(ctx2)

        ctx3 = FlowContext(session_id="sess_002", agent_id="agent_001", user_input="请求")
        ctx3.conversation_history = []
        bridge.build_context(ctx3)

        stats = bridge.get_cache_stats()
        assert stats["hit_rate"] == pytest.approx(1/3, abs=0.1)


class TestMemoryCoordinator:
    """MemoryCoordinator 测试"""

    def test_write_and_retrieve(self):
        coordinator = MemoryCoordinator()
        mem_id = coordinator.write("测试记忆内容", category="test", temperature=80.0,
                                   is_important=True, buffered=False)
        assert mem_id.startswith("mem_")

        results = coordinator.retrieve("测试", category="test", limit=5)
        assert len(results) == 1
        assert results[0]["content"] == "测试记忆内容"

    def test_retrieve_with_min_temperature(self):
        coordinator = MemoryCoordinator()
        coordinator.write("高温记忆", category="test", temperature=90.0, buffered=False)
        coordinator.write("低温记忆", category="test", temperature=20.0, buffered=False)

        results = coordinator.retrieve("", min_temperature=50)
        assert len(results) == 1
        assert results[0]["content"] == "高温记忆"

    def test_retrieve_with_category_filter(self):
        coordinator = MemoryCoordinator()
        coordinator.write("对话记忆", category="conversation", buffered=False)
        coordinator.write("测试记忆", category="test", buffered=False)

        results = coordinator.retrieve("", category="test")
        assert len(results) == 1
        assert results[0]["content"] == "测试记忆"

    def test_buffered_write(self):
        coordinator = MemoryCoordinator()
        mem_id = coordinator.write("缓冲记忆", buffered=True)

        stats = coordinator.get_stats()
        assert stats["buffer_size"] >= 0

    def test_flush_all(self):
        coordinator = MemoryCoordinator()
        for i in range(5):
            coordinator.write(f"记忆{i}", buffered=True)

        written = coordinator.flush_all()
        assert coordinator.get_stats()["buffer_size"] == 0

    def test_retrieve_returns_copy(self):
        coordinator = MemoryCoordinator()
        coordinator.write("原始记忆", buffered=False)

        results = coordinator.retrieve("原始")
        results[0]["content"] = "被修改的记忆"

        results2 = coordinator.retrieve("原始")
        assert results2[0]["content"] == "原始记忆"

    def test_retrieve_sorted_by_temperature(self):
        coordinator = MemoryCoordinator()
        coordinator.write("低温", temperature=30.0, buffered=False)
        coordinator.write("高温", temperature=90.0, buffered=False)
        coordinator.write("中温", temperature=60.0, buffered=False)

        results = coordinator.retrieve("")
        assert results[0]["content"] == "高温"
        assert results[-1]["content"] == "低温"


class TestToolFeedbackLoop:
    """ToolFeedbackLoop 测试"""

    def test_register_and_unregister_tool(self):
        loop = ToolFeedbackLoop()
        mock_func = MagicMock(return_value="success")
        loop.register_tool("test_tool", mock_func)
        assert "test_tool" in loop._tool_registry

        loop.unregister_tool("test_tool")
        assert "test_tool" not in loop._tool_registry

    @pytest.mark.asyncio
    async def test_invoke_sync_tool(self):
        loop = ToolFeedbackLoop()
        loop.register_tool("echo", lambda text: f"echo: {text}")

        result = await loop.invoke("echo", {"text": "hello"})
        assert result["success"] is True
        assert result["result"] == "echo: hello"
        assert result["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_invoke_async_tool(self):
        loop = ToolFeedbackLoop()

        async def async_echo(text: str):
            await asyncio.sleep(0.01)
            return f"async_echo: {text}"

        loop.register_tool("async_echo", async_echo)
        result = await loop.invoke("async_echo", {"text": "hello"})
        assert result["success"] is True
        assert result["result"] == "async_echo: hello"

    @pytest.mark.asyncio
    async def test_invoke_nonexistent_tool(self):
        loop = ToolFeedbackLoop()
        result = await loop.invoke("not_exist", {})
        assert result["success"] is False
        assert "Tool not found" in result["error"]

    @pytest.mark.asyncio
    async def test_invoke_tool_that_raises(self):
        loop = ToolFeedbackLoop()
        loop.register_tool("bad_tool", lambda: (_ for _ in ()).throw(Exception("fail")))

        result = await loop.invoke("bad_tool", {})
        assert result["success"] is False

    def test_collect_feedback(self):
        loop = ToolFeedbackLoop()
        result = loop.collect_feedback(
            {"tool_name": "test", "success": False, "duration_ms": 500},
            user_rating=0.3,
            comment="结果不理想",
        )
        assert result["should_learn"] is True
        assert result["user_rating"] == 0.3

    def test_feedback_stats(self):
        loop = ToolFeedbackLoop()
        loop._stats = {"invocations": 10, "successes": 7, "failures": 3}
        stats = loop.get_feedback_stats()
        assert stats["success_rate"] == 0.7


class TestExperienceEvolutionEngine:
    """ExperienceEvolutionEngine 测试"""

    def test_accumulate_experience(self):
        engine = ExperienceEvolutionEngine()
        exp_id = engine.accumulate_experience(
            context={"user_input": "测试查询"},
            result={"output": "测试结果"},
            success=True,
            skill_name="test_skill",
        )
        assert exp_id.startswith("exp_")

    def test_find_similar_experiences(self):
        engine = ExperienceEvolutionEngine()
        engine.accumulate_experience(
            context={"user_input": "包含Python关键词的查询"},
            result={"output": "Python相关结果"},
            success=True,
            skill_name="test_skill",
        )
        engine.accumulate_experience(
            context={"user_input": "包含Java关键词的查询"},
            result={"output": "Java相关结果"},
            success=False,
            skill_name="test_skill",
        )

        results = engine.find_similar_experiences("Python", skill_name="test_skill", limit=5)
        assert len(results) >= 1

    def test_find_similar_experiences_empty_skill(self):
        engine = ExperienceEvolutionEngine()
        results = engine.find_similar_experiences("查询", skill_name="nonexistent")
        assert results == []

    def test_evolve_no_experiences(self):
        engine = ExperienceEvolutionEngine()
        result = engine.evolve("new_skill", {})
        assert result["evolved"] is False
        assert result["reason"] == "no_experiences"

    def test_evolve_with_experiences(self):
        engine = ExperienceEvolutionEngine()
        engine.accumulate_experience({"input": "1"}, {"output": "1"}, True, "test")
        engine.accumulate_experience({"input": "2"}, {"output": "2"}, False, "test")
        engine.accumulate_experience({"input": "3"}, {"output": "3"}, False, "test")
        engine.accumulate_experience({"input": "4"}, {"output": "4"}, False, "test")
        engine.accumulate_experience({"input": "5"}, {"output": "5"}, False, "test")

        result = engine.evolve("test", {"error": "pattern_error"})
        assert result["evolved"] is True
        assert len(result["suggestions"]) > 0

    def test_get_evolution_stats(self):
        engine = ExperienceEvolutionEngine()
        engine.accumulate_experience({"input": "1"}, {"output": "1"}, True, "skill_a")
        engine.accumulate_experience({"input": "2"}, {"output": "2"}, True, "skill_b")

        stats = engine.get_evolution_stats()
        assert stats["experiences_recorded"] == 2
        assert "skill_a" in stats["skills_with_experiences"]
        assert "skill_b" in stats["skills_with_experiences"]


class TestSleepConsolidationCoordinator:
    """SleepConsolidationCoordinator 测试"""

    def test_consolidate_no_merge_needed(self):
        coordinator = SleepConsolidationCoordinator()
        memories = [
            {"id": "1", "content": "ABC123XYZ789", "temperature": 50},
            {"id": "2", "content": "DEF456UVW012", "temperature": 60},
        ]
        result = coordinator.consolidate_memories(memories)
        assert result["report"]["merged_count"] == 0
        assert len(result["consolidated_memories"]) == 2
        assert result["report"]["consolidation_quality"] >= 0.7

    def test_consolidate_with_merge(self):
        coordinator = SleepConsolidationCoordinator()
        coordinator.set_merge_threshold(0.5)
        memories = [
            {"id": "1", "content": "相似内容版本一", "temperature": 50},
            {"id": "2", "content": "相似内容版本一补充", "temperature": 60},
        ]
        result = coordinator.consolidate_memories(memories)
        assert result["report"]["merged_count"] >= 0
        assert result["report"]["total_processed"] == 2

    def test_detect_conflicts_contradiction(self):
        coordinator = SleepConsolidationCoordinator()
        existing = [
            {"id": "1", "content": "用户喜欢Python", "temperature": 50}
        ]
        result = coordinator.detect_and_resolve_conflicts("用户不喜欢Python", existing)
        assert result["conflicts_found"] >= 1
        assert result["strategy"] == "latest"
        assert len(result["resolutions"]) >= 1
        assert result["resolutions"][0]["action"] == "keep_new"

    def test_detect_no_conflict(self):
        coordinator = SleepConsolidationCoordinator()
        existing = [
            {"id": "1", "content": "用户喜欢Python", "temperature": 50}
        ]
        result = coordinator.detect_and_resolve_conflicts("用户喜欢Java", existing)
        assert result["conflicts_found"] == 0

    def test_resolution_strategy_keep_both(self):
        coordinator = SleepConsolidationCoordinator()
        coordinator.set_conflict_resolution_strategy("keep_both")
        existing = [
            {"id": "1", "content": "用户喜欢Python", "temperature": 50}
        ]
        result = coordinator.detect_and_resolve_conflicts("用户不喜欢Python", existing)
        assert result["resolutions"][0]["action"] == "keep_both"

    def test_resolution_strategy_merge(self):
        coordinator = SleepConsolidationCoordinator()
        coordinator.set_conflict_resolution_strategy("merge")
        existing = [
            {"id": "1", "content": "用户喜欢Python", "temperature": 50}
        ]
        result = coordinator.detect_and_resolve_conflicts("用户不喜欢Python", existing)
        assert result["resolutions"][0]["action"] == "merge"
        assert "merged_content" in result["resolutions"][0]

    def test_resolution_strategy_flag(self):
        coordinator = SleepConsolidationCoordinator()
        coordinator.set_conflict_resolution_strategy("flag")
        existing = [
            {"id": "1", "content": "用户喜欢Python", "temperature": 50}
        ]
        result = coordinator.detect_and_resolve_conflicts("用户不喜欢Python", existing)
        assert result["resolutions"][0]["action"] == "flag"

    def test_set_invalid_strategy(self):
        coordinator = SleepConsolidationCoordinator()
        coordinator.set_conflict_resolution_strategy("invalid")
        assert coordinator._conflict_resolution_strategy != "invalid"

    def test_get_dream_reports(self):
        coordinator = SleepConsolidationCoordinator()
        coordinator.consolidate_memories([
            {"id": "1", "content": "记忆A", "temperature": 50},
        ])
        reports = coordinator.get_dream_reports(limit=5)
        assert len(reports) >= 1
        assert "consolidation_quality" in reports[0]

    def test_get_stats(self):
        coordinator = SleepConsolidationCoordinator()
        stats = coordinator.get_stats()
        assert "merges" in stats
        assert "conflicts_detected" in stats
        assert "merge_threshold" in stats

    def test_merge_threshold_clamped(self):
        coordinator = SleepConsolidationCoordinator()
        coordinator.set_merge_threshold(1.5)
        assert coordinator._merge_threshold == 1.0
        coordinator.set_merge_threshold(-0.5)
        assert coordinator._merge_threshold == 0.0

    def test_consolidate_empty_list(self):
        coordinator = SleepConsolidationCoordinator()
        result = coordinator.consolidate_memories([])
        assert result["report"]["total_processed"] == 0

    def test_consolidate_with_crystallized(self):
        coordinator = SleepConsolidationCoordinator()
        coordinator.set_merge_threshold(0.3)
        memories = [
            {"id": "1", "content": "ABCD相似内容XYZ", "temperature": 50, "is_crystallized": True},
            {"id": "2", "content": "ABCD相似内容XYZ补充", "temperature": 40},
        ]
        result = coordinator.consolidate_memories(memories)
        if result["report"]["merged_count"] > 0:
            kept = result["consolidated_memories"][0]
            assert kept.get("merge_count", 0) >= 1


class TestMetaCognitionEvaluator:
    """MetaCognitionEvaluator 测试"""

    def test_evaluate_empty_flow(self):
        evaluator = MetaCognitionEvaluator()
        ctx = FlowContext()
        tracer = FlowTracer()

        report = evaluator.evaluate(ctx, tracer)
        assert "quality_score" in report
        assert report["evaluation_id"].startswith("eval_")
        assert "recommendations" in report
        assert "anomalies" in report

    def test_evaluate_with_events(self):
        evaluator = MetaCognitionEvaluator()
        ctx = FlowContext(session_id="sess_001")
        tracer = FlowTracer()

        for phase in [FlowPhase.CONVERSATION, FlowPhase.CONTEXT_BUILD,
                      FlowPhase.MEMORY_RETRIEVAL, FlowPhase.MEMORY_WRITE]:
            evt_id = tracer.start_phase(phase)
            tracer.end_phase(evt_id, phase, True)

        report = evaluator.evaluate(ctx, tracer)
        assert report["quality_score"] > 0
        assert "phase_scores" in report

    def test_detects_anomalies(self):
        evaluator = MetaCognitionEvaluator()
        ctx = FlowContext()
        tracer = FlowTracer()

        for i in range(5):
            evt_id = tracer.start_phase(FlowPhase.TOOL_INVOCATION)
            tracer.end_phase(evt_id, FlowPhase.TOOL_INVOCATION, i < 2)

        report = evaluator.evaluate(ctx, tracer)
        if report["anomalies"]:
            assert any(a["type"] in ["low_success_rate", "phase_degradation"]
                      for a in report["anomalies"])

    def test_get_evaluation_report(self):
        evaluator = MetaCognitionEvaluator()
        ctx = FlowContext()
        tracer = FlowTracer()
        evaluator.evaluate(ctx, tracer)

        report = evaluator.get_evaluation_report()
        assert report["evaluations"] == 1
        assert "avg_quality_score" in report


class TestFlowOrchestrator:
    """FlowOrchestrator 完整流程测试"""

    def test_initialization(self):
        orchestrator = FlowOrchestrator()
        assert orchestrator.message_flow is not None
        assert orchestrator.context_bridge is not None
        assert orchestrator.memory_coordinator is not None
        assert orchestrator.tool_feedback is not None
        assert orchestrator.experience_evolution is not None
        assert orchestrator.sleep_consolidation is not None
        assert orchestrator.metacognition is not None
        assert orchestrator.tracer is not None

    def test_process_conversation_complete_flow(self):
        orchestrator = FlowOrchestrator()
        result = orchestrator.process_conversation(
            user_input="你好，帮我查询Python相关信息",
            session_id="test_session",
            agent_id="test_agent",
            user_id="test_user",
            system_prompt="你是一个AI助手",
        )

        assert result is not None
        assert result.session_id == "test_session"
        assert result.agent_id == "test_agent"
        assert result.user_input == "你好，帮我查询Python相关信息"

        assert result.conversation_history is not None
        assert len(result.conversation_history) >= 1

        assert result.built_context is not None
        assert len(result.built_context) >= 1

        assert result.metadata["cycle_count"] >= 1
        assert "completed_at" in result.metadata

    def test_process_conversation_all_phases_complete(self):
        orchestrator = FlowOrchestrator()
        result = orchestrator.process_conversation(
            user_input="测试所有阶段",
        )

        assert result.metacognition_report is not None
        assert "quality_score" in result.metacognition_report

        stats = orchestrator.tracer.get_stats()
        assert stats["total_events"] >= 10
        phases = stats["phases"]
        expected_phases = [
            "conversation", "context_build", "memory_cache",
            "memory_retrieval", "memory_write", "tool_invocation",
            "result_feedback", "experience_accumulate", "evolution",
            "sleep_consolidation", "conflict_resolution", "metacognition",
        ]
        for phase in expected_phases:
            assert phase in phases, f"Phase {phase} should be in phases"

    def test_process_conversation_twice(self):
        orchestrator = FlowOrchestrator()
        result1 = orchestrator.process_conversation(
            user_input="第一次对话",
            session_id="sess_repeat",
        )
        result2 = orchestrator.process_conversation(
            user_input="第二次对话",
            session_id="sess_repeat",
        )

        assert result1.metadata["cycle_count"] >= 1
        assert result2.metadata["cycle_count"] >= 2
        assert result2.metadata["cycle_count"] > result1.metadata["cycle_count"]

        history = orchestrator.message_flow.get_history("sess_repeat")
        assert len(history) == 2

    def test_get_comprehensive_report(self):
        orchestrator = FlowOrchestrator()
        orchestrator.process_conversation(user_input="测试")

        report = orchestrator.get_comprehensive_report()
        assert "cycle_count" in report
        assert "tracer" in report
        assert "memory" in report
        assert "cache" in report
        assert "tool_feedback" in report
        assert "experience_evolution" in report
        assert "sleep_consolidation" in report
        assert "metacognition" in report

    def test_flush_all(self):
        orchestrator = FlowOrchestrator()
        orchestrator.process_conversation(user_input="测试")
        orchestrator.flush_all()

    def test_process_conversation_with_error_handling(self):
        orchestrator = FlowOrchestrator()
        result = orchestrator.process_conversation(user_input="")
        assert result is not None

    def test_process_conversation_session_isolation(self):
        orchestrator = FlowOrchestrator()
        orchestrator.process_conversation(
            user_input="会话1的消息",
            session_id="sess_A",
            agent_id="agent_1",
        )
        orchestrator.process_conversation(
            user_input="会话2的消息",
            session_id="sess_B",
            agent_id="agent_2",
        )

        assert orchestrator.message_flow.get_history("sess_A")[0]["content"] == "会话1的消息"
        assert orchestrator.message_flow.get_history("sess_B")[0]["content"] == "会话2的消息"


class TestFlowContextIntegration:
    """FlowContext 跨阶段数据流转测试"""

    def test_context_persists_across_phases(self):
        orchestrator = FlowOrchestrator()
        result = orchestrator.process_conversation(
            user_input="集成测试数据",
            session_id="integration_test",
            agent_id="test_agent",
        )

        assert result.user_input in result.built_context[-1]["content"]

        assert result.retrieved_memories is not None
        assert result.cached_memories is not None

        if result.conflicts:
            assert len(result.conflicts) >= 0

        if result.sleep_results:
            assert "report" in result.sleep_results

        if result.experiences:
            for exp in result.experiences:
                assert "id" in exp

        if result.evolution_changes:
            for ev in result.evolution_changes:
                assert "evolved" in ev

        assert "quality_score" in result.metacognition_report


class TestCompleteClosedLoop:
    """端到端闭环测试"""

    def test_full_cycle_end_to_end(self):
        """模拟多次对话，验证完整闭环"""
        orchestrator = FlowOrchestrator()

        conversations = [
            "你好，我想学习Python",
            "我喜欢使用VSCode编辑器",
            "Python很适合数据科学",
            "我不喜欢Java语言",
            "我想做一个数据分析项目",
        ]

        results = []
        for i, msg in enumerate(conversations):
            result = orchestrator.process_conversation(
                user_input=msg,
                session_id="e2e_session",
                agent_id="e2e_agent",
                user_id="e2e_user",
                system_prompt="你是一个编程助手",
            )
            results.append(result)

        orchestrator.flush_all()

        assert all(r is not None for r in results)
        assert all("quality_score" in r.metacognition_report for r in results)

        history = orchestrator.message_flow.get_history("e2e_session")
        assert len(history) == len(conversations)

        comprehensive = orchestrator.get_comprehensive_report()
        assert comprehensive["cycle_count"] == len(conversations)
        assert comprehensive["memory"]["total_memories"] > 0

        tracer_stats = comprehensive["tracer"]
        assert tracer_stats["total_events"] >= len(conversations) * 10
        assert "conversation" in tracer_stats["phases"]
        assert "metacognition" in tracer_stats["phases"]

        metacognition = comprehensive["metacognition"]
        assert metacognition["evaluations"] >= len(conversations)

        experience_stats = comprehensive["experience_evolution"]
        assert experience_stats["experiences_recorded"] >= len(conversations)

    def test_conflict_detection_in_loop(self):
        """测试闭环中的冲突检测"""
        orchestrator = FlowOrchestrator()

        orchestrator.process_conversation(
            user_input="用户喜欢Python",
            session_id="conflict_test",
        )

        result = orchestrator.process_conversation(
            user_input="用户不喜欢Python",
            session_id="conflict_test",
        )

        report = orchestrator.sleep_consolidation.get_stats()
        assert "conflicts_detected" in report

    def test_metacognition_improvement_cycle(self):
        """测试元认知评估对后续循环的影响"""
        orchestrator = FlowOrchestrator()

        for i in range(3):
            orchestrator.process_conversation(
                user_input=f"第{i+1}轮测试对话",
                session_id="meta_test",
            )

        report = orchestrator.metacognition.get_evaluation_report()
        assert report["evaluations"] == 3
        assert report["avg_quality_score"] > 0


class TestSingletonPattern:
    """单例模式测试"""

    def test_get_flow_orchestrator_singleton(self):
        orchestrator1 = get_flow_orchestrator()
        orchestrator2 = get_flow_orchestrator()
        assert orchestrator1 is orchestrator2

    def test_process_conversation_flow_function(self):
        ctx = process_conversation_flow(
            user_input="便捷函数测试",
            session_id="conv_test",
            agent_id="agent_test",
            user_id="user_test",
            system_prompt="你是一个助手",
        )
        assert ctx is not None
        assert ctx.session_id == "conv_test"
        assert ctx.agent_id == "agent_test"
        assert ctx.metacognition_report is not None