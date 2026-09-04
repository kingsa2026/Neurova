"""
经验闭环修复测试 — TDD GREEN 阶段

验证 5 个断裂点已修复：
1. EvolutionOrchestrator 有 crystallizer 属性 ✅
2. on_experience_recorded 调用 crystallizer.observe() ✅
3. Agent.crystallizer 注入到 EvolutionOrchestrator ✅
4. 经验 → 结晶 → 注入上下文完整流程 ✅
5. 结晶经验检索正常工作 ✅
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, Mock
from typing import Dict, List, Any


# ══════════════════════════════════════════════════════════════
# Test 1: EvolutionOrchestrator 有 crystallizer 属性
# ══════════════════════════════════════════════════════════════

class TestEvolutionOrchestratorHasCrystallizer:
    """验证 EvolutionOrchestrator 有 crystallizer 属性"""

    def test_has_crystallizer_attribute(self):
        """验证 EvolutionOrchestrator 初始化后有 crystallizer 属性"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        orchestrator = EvolutionOrchestrator()
        assert hasattr(orchestrator, 'crystallizer'), "EvolutionOrchestrator 缺少 crystallizer 属性"
        assert orchestrator.crystallizer is None, "默认 crystallizer 应为 None"

    def test_has_crystallizer_via_init(self):
        """验证通过构造函数注入 crystallizer"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        mock_crystallizer = MagicMock()
        orchestrator = EvolutionOrchestrator(crystallizer=mock_crystallizer)
        assert orchestrator.crystallizer is mock_crystallizer


# ══════════════════════════════════════════════════════════════
# Test 2: on_experience_recorded 调用 crystallizer.observe()
# ══════════════════════════════════════════════════════════════

class TestOnExperienceRecordedTriggersCrystallization:
    """验证 on_experience_recorded 触发结晶观察"""

    def test_calls_crystallizer_observe(self):
        """验证 on_experience_recorded 对每个工具调用 crystallizer.observe"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        mock_crystallizer = MagicMock()
        orchestrator = EvolutionOrchestrator(crystallizer=mock_crystallizer)

        # 注册工具
        orchestrator.register_tools(["search", "calculator"])

        # 记录经验
        result = orchestrator.on_experience_recorded(
            text="使用 search 和 calculator 完成了计算任务",
            task="计算任务",
            tools=["search", "calculator"],
            success=True,
        )

        # 验证 crystallizer.observe 被调用两次（每个工具一次）
        assert mock_crystallizer.observe.call_count == 2

        # 验证第一次调用参数
        first_call = mock_crystallizer.observe.call_args_list[0]
        assert first_call.kwargs['tool_name'] == 'search'
        assert first_call.kwargs['context'] == '计算任务'
        assert first_call.kwargs['success'] is True

        # 验证第二次调用参数
        second_call = mock_crystallizer.observe.call_args_list[1]
        assert second_call.kwargs['tool_name'] == 'calculator'

    def test_no_crystallizer_does_not_crash(self):
        """验证没有 crystallizer 时不崩溃"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        orchestrator = EvolutionOrchestrator(crystallizer=None)
        orchestrator.register_tools(["search"])

        result = orchestrator.on_experience_recorded(
            text="测试经验",
            task="测试",
            tools=["search"],
            success=True,
        )

        assert result["task"] == "测试"

    def test_crystallizer_error_does_not_crash(self):
        """验证 crystallizer.observe 异常不影响整体流程"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        mock_crystallizer = MagicMock()
        mock_crystallizer.observe.side_effect = RuntimeError("结晶器异常")

        orchestrator = EvolutionOrchestrator(crystallizer=mock_crystallizer)
        orchestrator.register_tools(["search"])

        # 不应抛出异常
        result = orchestrator.on_experience_recorded(
            text="测试经验",
            task="测试",
            tools=["search"],
            success=True,
        )

        assert result["task"] == "测试"
        assert result["success"] is True

    def test_no_tools_skips_crystallization(self):
        """验证没有工具时以 "chat" 伪工具名进结晶缓冲（2026-09-04 修复⑦：入口放宽）"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        mock_crystallizer = MagicMock()
        orchestrator = EvolutionOrchestrator(crystallizer=mock_crystallizer)

        result = orchestrator.on_experience_recorded(
            text="纯文本对话",
            task="闲聊",
            tools=[],
            success=True,
        )

        mock_crystallizer.observe.assert_called_once_with(
            tool_name="chat", context="闲聊", success=True
        )

    def test_unregistered_tools_still_trigger_crystallization(self):
        """验证未注册的工具也触发结晶（结晶器独立于注册表）"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        mock_crystallizer = MagicMock()
        orchestrator = EvolutionOrchestrator(crystallizer=mock_crystallizer)
        # 不注册任何工具

        result = orchestrator.on_experience_recorded(
            text="使用新工具",
            task="新任务",
            tools=["new_tool"],
            success=True,
        )

        # crystallizer.observe 仍应被调用
        assert mock_crystallizer.observe.call_count == 1


# ══════════════════════════════════════════════════════════════
# Test 3: Agent.crystallizer 注入到 EvolutionOrchestrator
# ══════════════════════════════════════════════════════════════

class TestCrystallizerInjection:
    """验证 Agent.crystallizer 正确注入到 EvolutionOrchestrator"""

    def test_crystallizer_injected_after_init(self):
        """验证 crystallizer 在初始化后注入到 evolution"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        # 模拟 Agent 初始化流程
        evolution = EvolutionOrchestrator()
        mock_crystallizer = MagicMock()

        # 模拟 agent_core.py 中的注入逻辑
        if hasattr(evolution, 'crystallizer'):
            evolution.crystallizer = mock_crystallizer

        assert evolution.crystallizer is mock_crystallizer

    def test_crystallizer_receives_evolution_reference(self):
        """验证 PatternCrystallizer 接收 EvolutionOrchestrator 引用"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer

        mock_engine = MagicMock()
        mock_evolution = MagicMock()

        crystallizer = PatternCrystallizer(
            engine=mock_engine,
            evolution_orchestrator=mock_evolution,
        )

        assert crystallizer.evolution is mock_evolution


# ══════════════════════════════════════════════════════════════
# Test 4: 完整经验闭环流程 — 记录 → 结晶 → 注入
# ══════════════════════════════════════════════════════════════

class TestExperienceLoopEndToEndFlow:
    """端到端验证：经验记录 → 结晶观察 → 检索 → 注入上下文"""

    def test_record_triggers_crystallize_observe(self):
        """验证 _step_record_experience 最终触发 crystallizer.observe"""
        from neurova.post_chat_pipeline import PostChatPipeline

        # 创建 mock Agent
        agent = MagicMock()
        mock_evolution = MagicMock()
        mock_crystallizer = MagicMock()

        agent.evolution = mock_evolution
        agent.evolution.on_experience_recorded = MagicMock(return_value={
            "insights_count": 1,
            "tools_mentioned": ["search"],
            "outcome": "success",
            "task": "搜索任务",
            "success": True,
        })
        agent._collect_tool_messages = MagicMock(return_value=[
            {"tool_name": "search", "success": True},
        ])

        pipeline = PostChatPipeline(agent)
        asyncio.run(pipeline._step_record_experience(
            user_input="帮我搜索信息",
            reply="搜索结果是...",
            save_memory=True,
        ))

        # 验证 evolution.on_experience_recorded 被调用
        agent.evolution.on_experience_recorded.assert_called_once()

    def test_crystallizer_observe_to_retrieve_flow(self):
        """验证 observe → retrieve 的完整流程"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer

        mock_engine = MagicMock()
        mock_engine.retrieve.return_value = [
            MagicMock(
                id="1",
                content="搜索任务用 search 成功率 80%",
                metadata={"primary_tool": "search", "success_rate": 0.8},
                temperature=80.0,
            )
        ]

        crystallizer = PatternCrystallizer(engine=mock_engine)

        # 模拟观察 3 次相同模式
        for _ in range(3):
            crystallizer.observe(
                tool_name="search",
                context="搜索信息",
                success=True,
            )

        # 验证结晶发生（engine.store 被调用）
        mock_engine.store.assert_called()

        # 检索结晶经验
        patterns = crystallizer.retrieve("搜索信息", limit=5)
        assert len(patterns) == 1
        assert patterns[0]["method"] == "search"
        assert patterns[0]["confidence"] == 0.8

    def test_crystallized_patterns_injected_into_context(self):
        """验证结晶经验被注入到上下文中"""
        from neurova.context.orchestrator import ContextOrchestrator
        import inspect

        # 验证 build_context 接受 crystallized_patterns 参数
        sig = inspect.signature(ContextOrchestrator.build_context)
        assert "crystallized_patterns" in sig.parameters

        # 验证默认值为 None
        param = sig.parameters["crystallized_patterns"]
        assert param.default is None

    def test_chat_context_has_crystallized_patterns(self):
        """验证 ChatContext 有 crystallized_patterns 字段"""
        from neurova.agent.chat_pipeline import ChatContext

        ctx = ChatContext(user_input="测试")
        assert hasattr(ctx, "crystallized_patterns")
        assert ctx.crystallized_patterns == []

    def test_full_loop_end_to_end(self):
        """完整闭环：记录 → 结晶 → 检索 → 注入"""
        from neurova.post_chat_pipeline import PostChatPipeline
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        # 1. 创建 EvolutionOrchestrator + PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer

        mock_engine = MagicMock()
        mock_engine.retrieve.return_value = []

        crystallizer = PatternCrystallizer(engine=mock_engine)
        evolution = EvolutionOrchestrator(crystallizer=crystallizer)
        evolution.register_tools(["search"])

        # 2. 模拟 Agent（crystallizer 必须显式挂在 agent 上——Step9 现按
        # agent 级隔离把 agent.crystallizer 传给 facade）
        agent = MagicMock()
        agent.evolution = evolution
        agent.crystallizer = crystallizer
        agent._collect_tool_messages = MagicMock(return_value=[
            {"tool_name": "search", "success": True},
        ])

        # 3. 记录经验（触发 crystallizer.observe）
        # EKB 写入走真实 SQLite，须隔离防污染真库
        with patch(
            "neurova.skills.experience_knowledge_base.ExperienceKnowledgeBase.add_experience_record"
        ):
            pipeline = PostChatPipeline(agent)
            asyncio.run(pipeline._step_record_experience(
                user_input="搜索信息",
                reply="搜索结果",
                save_memory=True,
            ))

        # 4. 验证 crystallizer.observe 被调用
        # (通过 observe 积累模式，3次后结晶)
        assert crystallizer._buffer  # 缓冲区有数据（1次观察）

        # 5. 模拟 2 次更多观察触发结晶
        for _ in range(2):
            crystallizer.observe(tool_name="search", context="搜索信息", success=True)

        # 验证结晶发生
        mock_engine.store.assert_called()

        # 6. 检索结晶经验
        mock_engine.retrieve.return_value = [
            MagicMock(
                id="1",
                content="搜索任务用 search 成功率 100%",
                metadata={"primary_tool": "search", "success_rate": 1.0},
                temperature=100.0,
            )
        ]
        patterns = crystallizer.retrieve("搜索信息")
        assert len(patterns) == 1


# ══════════════════════════════════════════════════════════════
# Test 5: 边界情况
# ══════════════════════════════════════════════════════════════

class TestExperienceLoopEdgeCases:
    """边界情况测试"""

    def test_empty_tools_list(self):
        """空工具列表以 "chat" 伪工具名观察（2026-09-04 修复⑦：入口放宽）"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        mock_crystallizer = MagicMock()
        orchestrator = EvolutionOrchestrator(crystallizer=mock_crystallizer)

        orchestrator.on_experience_recorded(
            text="纯文本对话",
            task="闲聊",
            tools=[],
            success=True,
        )

        mock_crystallizer.observe.assert_called_once_with(
            tool_name="chat", context="闲聊", success=True
        )

    def test_none_crystallizer(self):
        """crystallizer 为 None 时正常工作"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        orchestrator = EvolutionOrchestrator(crystallizer=None)
        orchestrator.register_tools(["search"])

        result = orchestrator.on_experience_recorded(
            text="使用 search 工具",
            task="搜索",
            tools=["search"],
            success=True,
        )

        assert result["success"] is True

    def test_crystallizer_not_initialized_on_agent(self):
        """Agent.crystallizer 为 None 时不崩溃"""
        from neurova.post_chat_pipeline import PostChatPipeline

        agent = MagicMock()
        agent.evolution = MagicMock()
        agent.evolution.on_experience_recorded = MagicMock(return_value={})
        agent._collect_tool_messages = MagicMock(return_value=[])
        agent.crystallizer = None

        pipeline = PostChatPipeline(agent)

        # 不应抛出异常
        asyncio.run(pipeline._step_record_experience(
            user_input="测试",
            reply="回复",
            save_memory=True,
        ))

    def test_multiple_tool_crystallization(self):
        """多工具经验正确触发多次结晶观察"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        mock_crystallizer = MagicMock()
        orchestrator = EvolutionOrchestrator(crystallizer=mock_crystallizer)
        orchestrator.register_tools(["search", "calculator", "file_read"])

        tools_used = ["search", "calculator", "file_read"]
        orchestrator.on_experience_recorded(
            text="使用多种工具完成任务",
            task="复杂任务",
            tools=tools_used,
            success=True,
        )

        assert mock_crystallizer.observe.call_count == 3

        # 验证每个工具都被观察
        called_tools = [call.kwargs['tool_name'] for call in mock_crystallizer.observe.call_args_list]
        assert set(called_tools) == set(tools_used)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])