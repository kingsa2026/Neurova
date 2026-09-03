"""
工具记忆闭环测试 — TDD 垂直切片

闭环流程: 用户输入 → check_tool_memory → 执行工具 → record_tool_usage → 下次匹配

测试聚焦于公共接口行为，不耦合实现细节。
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
from unittest.mock import Mock, MagicMock, patch
from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration


class TestRecordToolUsageComplete:
    """record_tool_usage 应该记录完整的工具使用信息"""

    def test_records_problem_text_and_tool_source(self):
        """记录用户输入和工具来源，用于后续匹配"""
        memory = ToolMemoryIntegration()
        
        memory.record_tool_usage(
            problem_text="帮我读取 config.json",
            tool_name="file_read",
            tool_source="skill_system",
            tool_params={"file_path": "config.json"},
            success=True,
            execution_time=0.5,
        )
        
        assert len(memory.usage_history) == 1
        record = memory.usage_history[0]
        assert record.tool_name == "file_read"
        assert record.success is True
        assert record.execution_time == 0.5
        # 关键：需要记录问题文本和工具来源
        assert record.context.get("problem_text") == "帮我读取 config.json"
        assert record.context.get("tool_source") == "skill_system"
        assert record.context.get("tool_params") == {"file_path": "config.json"}

    def test_records_failure_with_error(self):
        """记录失败的工具使用，包含错误信息"""
        memory = ToolMemoryIntegration()
        
        memory.record_tool_usage(
            problem_text="读取不存在的文件",
            tool_name="file_read",
            tool_source="skill_system",
            tool_params={"file_path": "missing.txt"},
            success=False,
            execution_time=0.1,
            error_msg="FileNotFoundError: missing.txt",
        )
        
        record = memory.usage_history[0]
        assert record.success is False
        assert record.context.get("error_msg") == "FileNotFoundError: missing.txt"


class TestCheckToolMemoryWithMuscleMemory:
    """check_tool_memory 应该使用肌肉记忆进行语义匹配"""

    def test_returns_matched_tool_from_muscle_memory(self):
        """肌肉记忆匹配成功时返回工具信息"""
        muscle_memory = Mock()
        mock_item = MagicMock()
        mock_item.tool_name = "file_read"
        mock_item.parameters = {"file_path": "{file_path}"}
        mock_item.metadata = {"tool_source": "skill_system"}
        mock_item.level = MagicMock()
        mock_item.level.value = "l2"
        muscle_memory.match_by_query.return_value = [(mock_item, 0.9)]
        
        memory = ToolMemoryIntegration(
            muscle_memory=muscle_memory,
            confidence_threshold=0.8,
        )
        
        result, decision = memory.check_tool_memory("帮我读取配置文件")
        
        assert result is not None
        assert result["tool_name"] == "file_read"
        assert result["confidence"] == 0.9
        muscle_memory.match_by_query.assert_called_once()

    def test_auto_execute_when_above_threshold(self):
        """置信度超过阈值时自动执行"""
        muscle_memory = Mock()
        mock_item = MagicMock()
        mock_item.tool_name = "file_read"
        mock_item.parameters = {}
        mock_item.metadata = {"tool_source": "skill_system"}
        mock_item.level = MagicMock()
        mock_item.level.value = "l1"
        muscle_memory.match_by_query.return_value = [(mock_item, 0.95)]
        
        memory = ToolMemoryIntegration(
            muscle_memory=muscle_memory,
            confidence_threshold=0.8,
        )
        
        _, decision = memory.check_tool_memory("读取文件")
        assert decision == "auto_execute"

    def test_suggest_when_below_threshold(self):
        """置信度低于阈值时建议"""
        muscle_memory = Mock()
        mock_item = MagicMock()
        mock_item.tool_name = "file_read"
        mock_item.parameters = {}
        mock_item.metadata = {"tool_source": "skill_system"}
        mock_item.level = MagicMock()
        mock_item.level.value = "l3"
        muscle_memory.match_by_query.return_value = [(mock_item, 0.6)]
        
        memory = ToolMemoryIntegration(
            muscle_memory=muscle_memory,
            confidence_threshold=0.8,
        )
        
        _, decision = memory.check_tool_memory("读取文件")
        assert decision == "suggest"

    def test_do_not_execute_when_no_match(self):
        """无匹配时不执行"""
        muscle_memory = Mock()
        muscle_memory.match_by_query.return_value = []
        
        memory = ToolMemoryIntegration(muscle_memory=muscle_memory)
        
        result, decision = memory.check_tool_memory("随便聊聊")
        assert result is None
        assert decision == "do_not_execute"

    def test_fallback_to_keyword_matching_without_muscle_memory(self):
        """没有肌肉记忆时降级到关键词匹配"""
        memory = ToolMemoryIntegration()
        memory.tool_stats["file_read"] = {"total": 10, "success": 9, "fail": 1, "avg_time": 0.5}
        
        result, decision = memory.check_tool_memory("帮我读取文件 config.json")
        
        assert result is not None
        assert result["tool_name"] == "file_read"


class TestDynamicThreshold:
    """动态置信度阈值"""

    def test_base_threshold_without_weights(self):
        """无权重时返回基础阈值"""
        memory = ToolMemoryIntegration(confidence_threshold=0.8)
        assert memory._get_dynamic_threshold("any_tool") == 0.8

    def test_high_weight_lowers_threshold(self):
        """高权重降低阈值"""
        from neurova.evolution.closed_loop import AdaptiveToolWeights
        weights = AdaptiveToolWeights()
        weights.register_tool("fast_tool", base_weight=2.5)
        
        memory = ToolMemoryIntegration(
            confidence_threshold=0.8,
            tool_weights=weights,
        )
        
        threshold = memory._get_dynamic_threshold("fast_tool")
        assert threshold < 0.8
        assert threshold >= 0.3

    def test_threshold_bounded_03_to_10(self):
        """阈值限制在 [0.3, 1.0]"""
        from neurova.evolution.closed_loop import AdaptiveToolWeights
        weights = AdaptiveToolWeights()
        weights.register_tool("extreme", base_weight=100.0)
        
        memory = ToolMemoryIntegration(
            confidence_threshold=0.8,
            tool_weights=weights,
        )
        
        threshold = memory._get_dynamic_threshold("extreme")
        assert 0.3 <= threshold <= 1.0


class TestFullLoop:
    """完整闭环：检查 → 执行 → 记录 → 再次检查"""

    def test_loop_learns_from_execution(self):
        """执行一次后，下次检查应该能匹配"""
        muscle_memory = Mock()
        
        # 第一次：无匹配
        muscle_memory.match.return_value = (None, None)
        
        memory = ToolMemoryIntegration(
            muscle_memory=muscle_memory,
            confidence_threshold=0.8,
        )
        
        # 第一次检查
        result1, decision1 = memory.check_tool_memory("读取配置文件")
        assert decision1 == "do_not_execute"
        
        # 模拟执行后记录
        memory.record_tool_usage(
            problem_text="读取配置文件",
            tool_name="file_read",
            tool_source="skill_system",
            tool_params={"file_path": "config.json"},
            success=True,
            execution_time=0.3,
        )
        
        # 验证统计已更新
        stats = memory.get_tool_stats("file_read")
        assert stats["total"] == 1
        assert stats["success"] == 1
        
        # 第二次：肌肉记忆匹配
        muscle_memory.match.return_value = (
            {"tool_name": "file_read", "tool_source": "skill_system", "score": 0.9},
            "l1"
        )
        
        result2, decision2 = memory.check_tool_memory("读取配置文件")
        assert decision2 == "auto_execute"
        assert result2["tool_name"] == "file_read"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
