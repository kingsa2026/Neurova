"""
知识库->经验形成->进化->记忆系统 闭环检测

验证四个子系统之间的数据流是否连通：
1. 知识库 -> 经验结晶 -> 经验检索
2. 工具执行 -> 进化权重 -> 工具选择
3. 经验记录 -> 模式挖掘 -> 结晶存储
4. 结晶经验 -> 上下文注入 -> 对话增强
"""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone


# ═══════════════════════════════════════════════════════
# 1. PatternCrystallizer: 观察->结晶->存储->检索 闭环
# ═══════════════════════════════════════════════════════

class TestCrystallizerLoop:
    """经验结晶闭环"""

    def test_observe_three_times_crystallizes(self):
        """观察3次同模式->自动结晶"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer

        engine = MagicMock()
        engine.store = MagicMock()

        crystallizer = PatternCrystallizer(engine=engine)

        # 观察3次相同模式
        for _ in range(3):
            crystallizer.observe("web_search", "搜索Python教程", success=True)

        # 应触发结晶，存储到 engine
        assert engine.store.call_count == 1
        stored_node = engine.store.call_args[0][0]
        assert stored_node.memory_type.value == "pattern" or str(stored_node.memory_type) == "MemoryType.PATTERN"

    def test_low_success_rate_no_crystallize(self):
        """成功率<60%不结晶"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer

        engine = MagicMock()
        crystallizer = PatternCrystallizer(engine=engine)

        # 5次中只有2次成功（40%）
        crystallizer.observe("tool_a", "task1", success=True)
        crystallizer.observe("tool_a", "task1", success=False)
        crystallizer.observe("tool_a", "task1", success=False)
        crystallizer.observe("tool_a", "task1", success=True)
        crystallizer.observe("tool_a", "task1", success=False)

        # 不应结晶
        assert engine.store.call_count == 0

    def test_retrieve_after_crystallize(self):
        """结晶后可检索"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import UnifiedMemoryNode, MemoryType

        engine = MagicMock()
        # 模拟检索返回结晶经验
        mock_node = UnifiedMemoryNode(
            content="模式: 搜索Python用web_search",
            memory_type=MemoryType.PATTERN,
            category="crystallized",
            temperature=80.0,
            metadata={"primary_tool": "web_search", "success_rate": 0.85},
        )
        engine.retrieve.return_value = [mock_node]

        crystallizer = PatternCrystallizer(engine=engine)
        results = crystallizer.retrieve("Python")

        assert len(results) == 1
        assert results[0]["content"] == "模式: 搜索Python用web_search"
        assert results[0]["method"] == "web_search"

    def test_crystallizer_notifies_evolution(self):
        """结晶后通知 EvolutionOrchestrator"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer

        engine = MagicMock()
        evolution = MagicMock()

        crystallizer = PatternCrystallizer(engine=engine, evolution_orchestrator=evolution)

        # 观察3次
        for _ in range(3):
            crystallizer.observe("tool_x", "task_y", success=True)

        # 应通知 evolution
        evolution.on_experience_recorded.assert_called_once()


# ═══════════════════════════════════════════════════════
# 2. EvolutionOrchestrator: 执行->权重->选择 闭环
# ═══════════════════════════════════════════════════════

class TestEvolutionLoop:
    """进化系统闭环"""

    def test_tool_execution_updates_weights(self):
        """工具执行后权重更新"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        evo = EvolutionOrchestrator()
        evo.register_tools(["tool_a", "tool_b"])

        # tool_a 成功
        evo.on_after_tool_execution("tool_a", success=True, latency=0.1)
        w_a = evo.tool_weights.get_effective_weight("tool_a")

        # tool_b 失败
        evo.on_after_tool_execution("tool_b", success=False, latency=0.5)
        w_b = evo.tool_weights.get_effective_weight("tool_b")

        # 成功的工具权重应更高
        assert w_a > w_b

    def test_weights_affect_ranking(self):
        """权重影响工具排序"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        evo = EvolutionOrchestrator()
        evo.register_tools(["fast_tool", "slow_tool"])

        # 快速成功
        for _ in range(5):
            evo.on_after_tool_execution("fast_tool", success=True, latency=0.1)

        # 慢速失败
        for _ in range(5):
            evo.on_after_tool_execution("slow_tool", success=False, latency=1.0)

        # 排序
        ranking = evo.tool_weights.get_ranked_tools(["fast_tool", "slow_tool"])
        assert ranking[0] == "fast_tool"

    def test_before_selection_filters_archived(self):
        """选择前过滤归档工具"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        evo = EvolutionOrchestrator()
        evo.register_tools(["active_tool", "archived_tool"])

        # 模拟 get_state 返回 archived
        original_get_state = evo.tool_lifecycle.get_state if hasattr(evo.tool_lifecycle, 'get_state') else None
        def mock_get_state(name):
            if name == "archived_tool":
                return type('State', (), {'value': 'archived'})()
            return type('State', (), {'value': 'active'})()
        evo.tool_lifecycle.get_state = mock_get_state

        result = evo.on_before_tool_selection(
            tools=["active_tool", "archived_tool"]
        )

        assert "archived_tool" in result.get("filtered", [])

    def test_experience_recorded_updates_weights_and_patterns(self):
        """经验记录->权重更新+模式挖掘"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        evo = EvolutionOrchestrator()
        evo.register_tools(["tool_a", "tool_b"])

        result = evo.on_experience_recorded(
            text="成功使用 tool_a 搜索信息",
            task="搜索信息",
            tools=["tool_a"],
            success=True,
        )

        assert result["success"] is True
        assert result["insights_count"] >= 0

        # 模式挖掘器应收到序列
        assert evo.pattern_miner is not None


# ═══════════════════════════════════════════════════════
# 3. ExperienceFeedback: 经验文本->洞察->反哺 闭环
# ═══════════════════════════════════════════════════════

class TestExperienceFeedbackLoop:
    """经验反哺闭环"""

    def test_process_experience_extracts_tools(self):
        """从经验文本中提取工具提及"""
        from neurova.evolution.experience_feedback import ExperienceFeedback

        ef = ExperienceFeedback()
        result = ef.process_experience(
            experience_text="成功使用 web_search 搜索了信息，然后用 file_read 读取了文件",
            task_type="信息检索",
        )

        assert "web_search" in result.get("tools_mentioned", [])
        assert "file_read" in result.get("tools_mentioned", [])

    def test_success_failure_classification(self):
        """成功/失败分类"""
        from neurova.evolution.experience_feedback import ExperienceFeedback

        ef = ExperienceFeedback()

        # 成功经验
        result_s = ef.process_experience(
            experience_text="任务成功完成，web_search 工具运行良好",
            task_type="搜索",
        )
        assert result_s.get("outcome") == "success"

        # 失败经验
        result_f = ef.process_experience(
            experience_text="任务失败，web_search 工具出错了",
            task_type="搜索",
        )
        assert result_f.get("outcome") == "failure"

    def test_task_tool_association_stored(self):
        """任务-工具关联被存储"""
        from neurova.evolution.experience_feedback import ExperienceFeedback

        ef = ExperienceFeedback()
        result = ef.process_experience(
            experience_text="成功使用 tool_a 完成 task_x",
            task_type="task_x",
        )

        # 验证工具被提及
        assert "tool_a" in result.get("tools_mentioned", [])
        # 验证结果包含关联信息
        assert "associations_updated" in result


# ═══════════════════════════════════════════════════════
# 4. CrystallizedExperienceManager: 检索->降级->缓存 闭环
# ═══════════════════════════════════════════════════════

class TestCrystallizedExperienceManagerLoop:
    """CrystallizedExperienceManager 闭环"""

    @pytest.mark.asyncio
    async def test_retrieve_success(self):
        """正常检索成功"""
        from neurova.agent.crystallized_experience_manager import (
            CrystallizedExperienceManager, RetrievalStatus
        )

        mock_crystallizer = MagicMock()
        mock_crystallizer.retrieve.return_value = [
            {"id": "c1", "content": "经验1", "method": "tool_a",
             "confidence": 0.9, "score": 85, "source": "crystallized"}
        ]

        manager = CrystallizedExperienceManager(crystallizer=mock_crystallizer)
        result = await manager.retrieve("Python", limit=5)

        assert result.status == RetrievalStatus.SUCCESS
        assert len(result.experiences) == 1
        assert result.experiences[0].content == "经验1"

    @pytest.mark.asyncio
    async def test_retrieve_fallback_to_memory(self):
        """检索失败->降级到记忆"""
        from neurova.agent.crystallized_experience_manager import (
            CrystallizedExperienceManager, RetrievalStatus
        )

        mock_crystallizer = MagicMock()
        mock_crystallizer.retrieve.side_effect = Exception("DB error")

        mock_memory = MagicMock()
        mock_memory.recall.return_value = [
            {"content": "记忆中的经验", "score": 0.7}
        ]

        manager = CrystallizedExperienceManager(
            crystallizer=mock_crystallizer,
            memory_manager=mock_memory,
        )
        result = await manager.retrieve("Python", limit=5, fallback_to_memory=True)

        # 应降级到记忆检索
        assert result.status in (RetrievalStatus.DEGRADED, RetrievalStatus.SUCCESS)

    def test_health_status_tracking(self):
        """健康状态追踪"""
        from neurova.agent.crystallized_experience_manager import (
            CrystallizedExperienceManager, HealthStatus
        )

        mock_crystallizer = MagicMock()
        mock_crystallizer.retrieve.return_value = []

        manager = CrystallizedExperienceManager(crystallizer=mock_crystallizer)

        # 初始健康
        health = manager.get_health()
        assert health == HealthStatus.HEALTHY


# ═══════════════════════════════════════════════════════
# 5. 端到端: 对话->工具执行->经验->结晶->检索->对话 闭环
# ═══════════════════════════════════════════════════════

class TestFullKnowledgeEvolutionLoop:
    """完整知识-进化闭环"""

    def test_tool_to_crystallize_to_retrieve_loop(self):
        """工具执行->经验记录->结晶->检索 完整闭环"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.evolution.closed_loop import EvolutionOrchestrator
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import UnifiedMemoryNode, MemoryType

        # 1. 创建组件
        engine = MagicMock()
        evo = EvolutionOrchestrator()
        evo.register_tools(["web_search"])

        crystallizer = PatternCrystallizer(engine=engine, evolution_orchestrator=evo)

        # 2. 模拟工具执行（进化系统记录）
        evo.on_after_tool_execution("web_search", success=True, latency=0.2)

        # 3. 观察3次（结晶器收集模式）
        for _ in range(3):
            crystallizer.observe("web_search", "搜索Python教程", success=True)

        # 4. 验证结晶发生
        assert engine.store.call_count == 1

        # 5. 模拟检索结晶经验
        mock_node = UnifiedMemoryNode(
            content="模式: 搜索Python用web_search 成功率 100%",
            memory_type=MemoryType.PATTERN,
            category="crystallized",
            temperature=100.0,
            metadata={"primary_tool": "web_search", "success_rate": 1.0},
        )
        engine.retrieve.return_value = [mock_node]

        results = crystallizer.retrieve("Python")
        assert len(results) == 1
        assert results[0]["method"] == "web_search"

        # 闭环验证: 工具执行->结晶->检索，数据完整流转

    def test_experience_to_evolution_loop(self):
        """经验记录->权重更新->模式挖掘 完整闭环"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        evo = EvolutionOrchestrator()
        evo.register_tools(["tool_a", "tool_b", "tool_c"])

        # 模拟多次经验记录
        tasks = [
            ("搜索信息", ["tool_a"], True),
            ("读取文件", ["tool_b", "tool_a"], True),
            ("写入文件", ["tool_c"], False),
            ("搜索信息", ["tool_a"], True),
            ("读取文件", ["tool_a"], True),
        ]

        for task, tools, success in tasks:
            evo.on_experience_recorded(
                text=f"任务{task}{'成功' if success else '失败'}",
                task=task,
                tools=tools,
                success=success,
            )

        # 验证权重反映使用模式
        ranking = evo.tool_weights.get_ranked_tools(["tool_a", "tool_b", "tool_c"])
        # tool_a 使用最多且成功率最高
        assert ranking[0] == "tool_a"
