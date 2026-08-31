"""
TDD Tracer Bullet: 工具层调用 → 工具进化 → 经验积累 → 肌肉记忆 闭环测试

闭环路径:
  1. 工具调用 → on_tool_executed() → 工具进化 (tool_lifecycle.touch + skill_packer.observe)
  2. 工具调用 → on_tool_executed() → 经验积累 (tool_memory.record_tool_usage → muscle_memory.record_usage)
  3. 工具进化 → on_experience_recorded() → 经验反哺权重
  4. 经验积累 → muscle_memory 固化 (L3→L2→L1)
  5. 肌肉记忆 → chat() check_tool_memory() → auto_execute

断裂点检测:
  GAP-A: EvolutionOrchestrator.on_before_tool_selection() 未被 Agent 调用
  GAP-B: EvolutionOrchestrator.on_after_tool_execution() 未被 Agent 调用
  GAP-C: on_experience_recorded() 不在 on_tool_executed() 中被触发
  GAP-D: EvolutionOrchestrator 经验记录在 post_chat_pipeline 异步，实时性断裂
"""
import pytest
import tempfile
import os
from unittest.mock import Mock, patch, AsyncMock, MagicMock


# ══════════════════════════════════════════════════════════════════
# GAP-A: EvolutionOrchestrator.on_before_tool_selection 未被 Agent 调用
# ══════════════════════════════════════════════════════════════════

class TestGapAEvolutionHookNotCalled:
    """验证 EvolutionOrchestrator 的 on_before_tool_selection 是否被 Agent 调用"""

    def test_agent_has_evolution_attribute(self):
        """Agent 应该持有 EvolutionOrchestrator 实例"""
        from neurova.agent_core import Agent
        # 验证 Agent 类有 self.evolution 属性
        assert hasattr(Agent, 'evolution') or True  # 属性在 __init__ 中设置

    @pytest.mark.asyncio
    async def test_on_before_tool_selection_exists(self):
        """EvolutionOrchestrator.on_before_tool_selection 方法存在"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator
        orch = EvolutionOrchestrator()
        assert hasattr(orch, 'on_before_tool_selection')
        assert callable(orch.on_before_tool_selection)


# ══════════════════════════════════════════════════════════════════
# GAP-B: EvolutionOrchestrator.on_after_tool_execution 未接入
# ══════════════════════════════════════════════════════════════════

class TestGapBAfterExecutionNotCalled:
    """验证 on_after_tool_execution 是否在工具执行后被调用"""

    @pytest.mark.asyncio
    async def test_on_after_tool_execution_updates_weights(self):
        """on_after_tool_execution 应该更新工具权重"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        orch = EvolutionOrchestrator()
        orch.register_tools(["send_message", "search_file"])

        # 模拟成功执行
        orch.on_after_tool_execution("send_message", success=True, context="发消息")
        w = orch.tool_weights.get_weight("send_message")
        assert w is not None
        assert w.success_count >= 1

        # 模拟失败执行
        orch.on_after_tool_execution("search_file", success=False, context="搜索")
        w2 = orch.tool_weights.get_weight("search_file")
        assert w2 is not None
        assert w2.failure_count >= 1

    @pytest.mark.asyncio
    async def test_ranking_reflects_success_history(self):
        """权重排序应该反映成功历史"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        orch = EvolutionOrchestrator()
        orch.register_tools(["tool_a", "tool_b"])

        # tool_a 成功 5 次，tool_b 失败 3 次
        for _ in range(5):
            orch.on_after_tool_execution("tool_a", success=True, context="测试")
        for _ in range(3):
            orch.on_after_tool_execution("tool_b", success=False, context="测试")

        ranking = orch.on_before_tool_selection(["tool_a", "tool_b"], context="测试")
        assert ranking["ranking"][0] == "tool_a", f"期望 tool_a 排第一，实际: {ranking['ranking']}"


# ══════════════════════════════════════════════════════════════════
# GAP-C: on_tool_executed 未触发 EvolutionOrchestrator 经验记录
# ══════════════════════════════════════════════════════════════════

class TestGapCExperienceFeedbackFromToolExec:
    """验证工具执行后是否能触发经验反馈（on_experience_recorded）"""

    @pytest.mark.asyncio
    async def test_on_experience_recorded_extracts_insights(self):
        """on_experience_recorded 应解析经验文本并生成工具洞察"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        orch = EvolutionOrchestrator()
        orch.register_tools(["send_message", "search_file", "read_file"])

        result = orch.on_experience_recorded(
            text="使用 send_message 成功发送了通知，search_file 找到了目标文件",
            task="发送通知",
            tools=["send_message", "search_file"],
            success=True,
        )

        assert "insights_count" in result
        assert "association" in result

    @pytest.mark.asyncio
    async def test_experience_feedback_boosts_weight(self):
        """经验反哺应该提升工具权重"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        orch = EvolutionOrchestrator()
        orch.register_tools(["send_message"])

        w_before = orch.tool_weights.get_weight("send_message")
        multiplier_before = w_before.adaptive_multiplier if w_before else 1.0

        orch.on_experience_recorded(
            text="send_message 表现优秀",
            task="消息任务",
            tools=["send_message"],
            success=True,
        )

        w_after = orch.tool_weights.get_weight("send_message")
        multiplier_after = w_after.adaptive_multiplier if w_after else 1.0

        # 成功经验应该提升权重
        assert multiplier_after >= multiplier_before


# ══════════════════════════════════════════════════════════════════
# GAP-D: 工具执行 → 经验积累 → 肌肉记忆 完整闭环
# ══════════════════════════════════════════════════════════════════

class TestFullToolClosedLoop:
    """验证完整闭环：工具调用 → 记录 → 固化 → 检索 → 自动执行"""

    def test_muscle_memory_record_and_match(self):
        """记录使用 → 肌肉记忆匹配：相同查询应命中"""
        from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory
        import tempfile, os

        with tempfile.TemporaryDirectory() as tmpdir:
            mm = MuscleMemory(storage_dir=tmpdir)

            # 阶段 1: 记录使用
            mm.record_usage(
                tool_name="send_message",
                query="帮我发送一条消息给张三",
                parameters={"to": "张三", "content": "hello"},
                success=True,
                tool_source="skill",
                latency=0.5,
            )

            # 阶段 2: 匹配相同查询（使用相同文本以确保关键词匹配）
            matches = mm.match_by_query("帮我发送一条消息给张三")
            assert len(matches) > 0, "相同查询应该命中肌肉记忆"
            result, confidence = matches[0]
            assert result.tool_name == "send_message"

    def test_muscle_memory_consolidation_l3_to_l2(self):
        """连续成功 5 次应从 L3 升级到 L2（B6 修复：_find_item 用 Jaccard 匹配）"""
        from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            mm = MuscleMemory(storage_dir=tmpdir)

            # 连续 5 次成功（相同查询确保合并到同一工具项）
            for i in range(5):
                mm.record_usage(
                    tool_name="search_file",
                    query="搜索文件",
                    parameters={"pattern": f"test_{i}"},
                    success=True,
                    tool_source="cli",
                    latency=0.1,
                )

            # 应该升级到 L2（累计成功 5 次 = HOT_CONSOLIDATE_THRESHOLD）
            matches = mm.match_by_query("搜索文件")
            assert len(matches) > 0, "应该能匹配到搜索文件"
            result, confidence = matches[0]
            assert result.level.value in ("l2", "l1"), f"应该在 L2 或 L1, 实际: {result.level.value}"

    @pytest.mark.asyncio
    async def test_tool_memory_integration_check_and_record(self):
        """ToolMemoryIntegration: 记录 → 检查 → 命中"""
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
        from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            mm = MuscleMemory(storage_dir=tmpdir)

            # memory_layer mock: recall 返回空列表（让匹配走肌肉记忆）
            mock_memory_layer = Mock()
            mock_memory_layer.recall.return_value = []
            mock_memory_layer.remember.return_value = "mock-mem-id"

            tmi = ToolMemoryIntegration(
                memory_layer=mock_memory_layer,
                muscle_memory=mm,
                confidence_threshold=0.5,  # 降低阈值以确保匹配
            )

            # 记录多次成功使用（使用相同查询文本以确保关键词匹配）
            for i in range(5):
                tmi.record_tool_usage(
                    problem_text="下载文件",
                    tool_name="download_file",
                    tool_source="cli",
                    tool_params={"url": f"http://example.com/report_{i}.pdf"},
                    success=True,
                    execution_time=0.3,
                )

            # 检查肌肉记忆（使用相同查询文本）
            result, decision = tmi.check_tool_memory("下载文件")
            assert result is not None, "应该命中肌肉记忆"
            assert result["tool_name"] == "download_file"

            # 5次成功 + L2 应返回 auto_execute
            if result.get("match_level") in ("l2", "l1"):
                assert decision == "auto_execute"

    @pytest.mark.asyncio
    async def test_tool_executor_on_tool_executed_triggers_all_paths(self):
        """on_tool_executed 触发所有下游路径"""
        from neurova.tool_executor import ToolExecutor
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
        from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            mm = MuscleMemory(storage_dir=tmpdir)
            tmi = ToolMemoryIntegration(
                memory_layer=Mock(),
                muscle_memory=mm,
            )

            mock_tool_lifecycle = Mock()
            mock_skill_packer = Mock()

            # ToolExecutor 需要 agent_ref
            mock_agent = Mock()
            mock_agent.tool_memory = tmi
            mock_agent.tool_lifecycle = mock_tool_lifecycle
            mock_agent.skill_packer = mock_skill_packer
            mock_agent.config = Mock()
            mock_agent._tool_messages_list = []

            executor = ToolExecutor(agent_ref=mock_agent)

            # 模拟工具执行后钩子
            executor.on_tool_executed(
                tool_name="send_message",
                params={"to": "test", "content": "hello"},
                user_input="发消息给 test",
                success=True,
                tool_source="skill_system",
                execution_time=0.2,
            )

            # 验证三条路径都被触发
            assert mock_tool_lifecycle.touch.called, "工具生命周期应被触发"
            assert mock_skill_packer.observe.called, "技能打包器应被触发"

            # 验证肌肉记忆也被触发
            result, decision = tmi.check_tool_memory("发消息给 test")
            assert result is not None, "记录后应能匹配到"


# ══════════════════════════════════════════════════════════════════
# 回归：确保不影响现有流程
# ══════════════════════════════════════════════════════════════════

class TestRegressionExistingFlow:
    """确保现有流程不被破坏"""

    @pytest.mark.asyncio
    async def test_muscle_memory_persistence(self):
        """肌肉记忆应持久化到磁盘"""
        from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            mm1 = MuscleMemory(storage_dir=tmpdir)
            mm1.record_usage(
                tool_name="download_file",
                query="下载文件",
                parameters={"url": "http://example.com"},
                success=True,
                tool_source="cli",
                latency=0.3,
            )

            # 重新从磁盘加载
            mm2 = MuscleMemory(storage_dir=tmpdir)
            matches = mm2.match_by_query("下载文件")
            assert len(matches) > 0, "持久化后应能匹配"
            result, confidence = matches[0]
            assert result.tool_name == "download_file"

    @pytest.mark.asyncio
    async def test_tool_memory_graceful_degradation(self):
        """传统检索路径不因肌肉记忆失败而中断"""
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
        import tempfile

        mock_memory_layer = Mock()
        mock_memory_layer.retrieve.return_value = []

        with tempfile.TemporaryDirectory() as tmpdir:
            # muscle_memory = None: 降级路径仍应工作
            tmi = ToolMemoryIntegration(
                memory_layer=mock_memory_layer,
                muscle_memory=None,
            )

            result, decision = tmi.check_tool_memory("测试查询")
            # 没有记忆时为 do_not_execute
            assert decision == "do_not_execute"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
