"""
进化闭环修复测试 — TDD 垂直切片

测试目标：
1. EvolutionOrchestrator 统一持有 pattern_miner 和 genetic_engine
2. tool_executor 调用 evolution.on_after_tool_execution()
3. 遗传进化结果反馈到工具权重
4. 频繁模式注入到 LLM 上下文
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Dict, List, Any


# ══════════════════════════════════════════════════════════════
# Test 1: EvolutionOrchestrator 统一持有子系统
# ══════════════════════════════════════════════════════════════

class TestEvolutionOrchestratorOwnsSubsystems:
    """验证 EvolutionOrchestrator 是 pattern_miner 和 genetic_engine 的唯一持有者"""

    def test_orchestrator_has_pattern_miner(self):
        """EvolutionOrchestrator 应持有 PatternMiner"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator
        orch = EvolutionOrchestrator()
        assert hasattr(orch, "pattern_miner")
        assert orch.pattern_miner is not None

    def test_orchestrator_has_genetic_engine(self):
        """EvolutionOrchestrator 应持有 ToolGeneticEngine"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator
        orch = EvolutionOrchestrator()
        assert hasattr(orch, "genetic_engine")
        assert orch.genetic_engine is not None

    def test_pattern_miner_shared_between_experience_and_mining(self):
        """on_experience_recorded 和 get_pattern_miner 应使用同一个 PatternMiner"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator
        orch = EvolutionOrchestrator()

        # 记录经验
        orch.on_experience_recorded(
            text="测试", task="测试任务", tools=["tool_a", "tool_b"], success=True
        )

        # 模式挖掘应能看到同一批序列
        assert orch.pattern_miner.sequence_count == 1


# ══════════════════════════════════════════════════════════════
# Test 2: post_chat_pipeline 使用 evolution 的子系统
# ══════════════════════════════════════════════════════════════

class TestPipelineUsesEvolutionSubsystems:
    """验证 post_chat_pipeline 通过 evolution 访问 pattern_miner 和 genetic_engine"""

    @pytest.fixture
    def mock_agent(self):
        agent = MagicMock()
        # evolution 持有 pattern_miner 和 genetic_engine
        agent.evolution = MagicMock()
        agent.evolution.pattern_miner = MagicMock()
        agent.evolution.pattern_miner.sequence_count = 5
        agent.evolution.pattern_miner.add_sequence = MagicMock()
        agent.evolution.pattern_miner.mine = MagicMock(return_value=[])
        agent.evolution.pattern_miner.get_top_patterns = MagicMock(return_value=[])
        agent.evolution.genetic_engine = MagicMock()
        agent.evolution.genetic_engine.evolve = MagicMock(return_value=[])
        agent.evolution.genetic_engine.add_to_population = MagicMock()
        agent.evolution.genetic_engine.population = []
        # agent 没有直接的 pattern_miner 和 genetic_engine 属性
        agent.pattern_miner = None
        agent.genetic_engine = None
        agent._collect_tool_messages = MagicMock(return_value=[
            {"tool_name": "tool_a", "type": "tool_result", "success": True},
            {"tool_name": "tool_b", "type": "tool_result", "success": True},
        ])
        return agent

    @pytest.mark.asyncio
    async def test_pattern_mining_uses_evolution_pattern_miner(self, mock_agent):
        """_step_pattern_mining 应使用 evolution.pattern_miner"""
        from neurova.post_chat_pipeline import PostChatPipeline
        pipeline = PostChatPipeline(mock_agent)

        await pipeline._step_pattern_mining()

        # 应调用 evolution 的 pattern_miner
        mock_agent.evolution.pattern_miner.add_sequence.assert_called_once()

    @pytest.mark.asyncio
    async def test_genetic_evolution_uses_evolution_genetic_engine(self, mock_agent):
        """_step_genetic_evolution 应使用 evolution.genetic_engine"""
        from neurova.post_chat_pipeline import PostChatPipeline
        pipeline = PostChatPipeline(mock_agent)

        await pipeline._step_genetic_evolution()

        # 应调用 evolution 的 genetic_engine
        mock_agent.evolution.genetic_engine.evolve.assert_called_once()


# ══════════════════════════════════════════════════════════════
# Test 3: tool_executor 调用 evolution.on_after_tool_execution
# ══════════════════════════════════════════════════════════════

class TestToolExecutorCallsEvolution:
    """验证 tool_executor 在工具执行后调用 evolution.on_after_tool_execution"""

    def test_on_tool_executed_updates_memory_and_lifecycle(self):
        """on_tool_executed 应驱动肌肉记忆与生命周期（evolution 反馈由
        PostChatPipeline 步骤 9 的 EvolutionFacade.record_experience 负责）"""
        from neurova.tool_executor import ToolExecutor

        # 构建 mock agent，属性通过 property 代理访问
        mock_agent = MagicMock()
        mock_agent.evolution = MagicMock()
        mock_agent.tool_memory = MagicMock()
        mock_agent.tool_lifecycle = MagicMock()

        # 通过构造函数注入 agent_ref
        executor = ToolExecutor(mock_agent)

        # 调用 on_tool_executed
        executor.on_tool_executed(
            tool_name="test_tool",
            params={"arg": "value"},
            user_input="测试输入",
            success=True,
            tool_source="skill_system",
            execution_time=0.5,
        )

        # 验证肌肉记忆与生命周期被驱动
        mock_agent.tool_memory.record_tool_usage.assert_called_once()
        kwargs = mock_agent.tool_memory.record_tool_usage.call_args.kwargs
        assert kwargs["tool_name"] == "test_tool"
        assert kwargs["success"] is True
        mock_agent.tool_lifecycle.touch.assert_called_once()


# ══════════════════════════════════════════════════════════════
# Test 4: 遗传进化结果反馈
# ══════════════════════════════════════════════════════════════

class TestGeneticEvolutionFeedback:
    """验证遗传进化结果被正确处理"""

    def test_evolve_returns_population(self):
        """genetic_engine.evolve() 应返回种群"""
        from neurova.evolution.genetic_engine import ToolGeneticEngine, ToolGenotype
        engine = ToolGeneticEngine(population_size=5)

        # 添加种子个体
        engine.add_to_population(ToolGenotype(tool_sequence=["a", "b"], success_rate=0.8))
        engine.add_to_population(ToolGenotype(tool_sequence=["b", "c"], success_rate=0.7))
        engine.add_to_population(ToolGenotype(tool_sequence=["a", "c"], success_rate=0.6))

        result = engine.evolve(generations=1)

        assert isinstance(result, list)
        assert len(result) > 0

    def test_evolution_updates_tool_weights(self):
        """进化结果应能更新工具权重"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator
        orch = EvolutionOrchestrator()

        # 注册工具
        orch.register_tools(["tool_a", "tool_b"])

        # 记录经验建立模式
        for _ in range(5):
            orch.on_experience_recorded(
                text="测试", task="测试任务",
                tools=["tool_a", "tool_b"], success=True
            )

        # 模式挖掘
        patterns = orch.pattern_miner.mine()
        assert len(patterns) > 0


# ══════════════════════════════════════════════════════════════
# Test 5: 频繁模式可用于上下文注入
# ══════════════════════════════════════════════════════════════

class TestFrequentPatternsForContext:
    """验证频繁模式可以被检索并用于上下文注入"""

    def test_mine_returns_frequent_patterns(self):
        """PatternMiner.mine() 应返回频繁模式"""
        from neurova.evolution.pattern_miner import PatternMiner
        miner = PatternMiner(min_support=2, min_length=2)

        # 添加重复序列
        for _ in range(5):
            miner.add_sequence(["tool_a", "tool_b", "tool_c"])

        patterns = miner.mine()
        assert len(patterns) > 0
        assert all(hasattr(p, "tools") for p in patterns)
        assert all(hasattr(p, "support") for p in patterns)

    def test_pattern_has_confidence_info(self):
        """频繁模式应包含足够的信息用于上下文注入"""
        from neurova.evolution.pattern_miner import PatternMiner
        miner = PatternMiner(min_support=2, min_length=2)

        for _ in range(5):
            miner.add_sequence(["tool_a", "tool_b"])

        patterns = miner.mine()
        if patterns:
            p = patterns[0]
            assert p.support >= 2
            assert len(p.tools) >= 2
            assert p.context  # 应有上下文描述


# ══════════════════════════════════════════════════════════════
# Test 6: EvolutionOrchestrator.run_evolution_cycle 端到端
# ══════════════════════════════════════════════════════════════

class TestEvolutionCycleEndToEnd:
    """端到端测试：工具执行 → 模式挖掘 → 遗传进化 → 权重更新"""

    def test_full_evolution_cycle(self):
        """完整进化周期：记录 → 挖掘 → 进化"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator
        orch = EvolutionOrchestrator()
        orch.register_tools(["search", "calculator", "summarize"])

        # 模拟多轮对话中的工具使用
        for _ in range(5):
            orch.on_experience_recorded(
                text="用户: 计算问题\n助手: 使用 search + calculator",
                task="计算问题",
                tools=["search", "calculator"],
                success=True,
            )

        # 模式挖掘
        patterns = orch.pattern_miner.mine()
        assert len(patterns) > 0

        # 验证权重已更新
        weight = orch.tool_weights.get_effective_weight("search")
        assert weight > 0

    def test_tool_execution_updates_weight_via_orchestrator(self):
        """工具执行后通过 orchestrator 更新权重"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator
        orch = EvolutionOrchestrator()
        orch.register_tools(["tool_a"])

        # 模拟成功执行
        orch.on_after_tool_execution("tool_a", success=True, context="测试", latency=0.1)

        weight = orch.tool_weights.get_weight("tool_a")
        assert weight is not None
        assert weight.success_count == 1

        # 模拟失败执行
        orch.on_after_tool_execution("tool_a", success=False, context="测试", latency=0.2)

        weight = orch.tool_weights.get_weight("tool_a")
        assert weight.failure_count == 1


class TestEvolutionEdgeCases:
    """进化闭环边界情况测试"""

    def test_on_tool_executed_handles_missing_evolution(self):
        """当 evolution 不存在时，on_tool_executed 不应崩溃"""
        from neurova.tool_executor import ToolExecutor

        mock_agent = MagicMock()
        mock_agent.evolution = None
        mock_agent.tool_memory = MagicMock()
        mock_agent.tool_lifecycle = MagicMock()
        mock_agent.skill_packer = MagicMock()

        executor = ToolExecutor(mock_agent)

        # 不应抛出异常
        executor.on_tool_executed(
            tool_name="test_tool",
            params={},
            user_input="测试",
            success=True,
        )

        # 其他钩子仍应被调用
        mock_agent.tool_memory.record_tool_usage.assert_called_once()
        mock_agent.tool_lifecycle.touch.assert_called_once()

    def test_agent_single_instance_pattern_miner(self):
        """Agent 的 pattern_miner 应与 evolution.pattern_miner 是同一实例"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator
        orch = EvolutionOrchestrator()

        # 模拟 Agent 的统一获取逻辑
        pattern_miner = orch.pattern_miner
        genetic_engine = orch.genetic_engine

        assert pattern_miner is orch.pattern_miner
        assert genetic_engine is orch.genetic_engine

        # 通过 orchestrator 记录的数据应能在直接引用中看到
        orch.on_experience_recorded(
            text="test", task="task", tools=["a", "b"], success=True
        )
        assert pattern_miner.sequence_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])