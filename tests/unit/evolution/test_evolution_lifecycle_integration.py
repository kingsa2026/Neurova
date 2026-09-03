"""
EvolutionOrchestrator 生命周期集成测试

测试内容：
1. 工具选择时过滤归档/冻结工具
2. DEGRADED工具降权30%
3. 工具执行后更新生命周期状态
4. 定期评估生命周期状态
5. 统计报告包含生命周期信息
"""
import sys
import time
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
from unittest.mock import Mock, MagicMock, patch
from neurova.evolution.closed_loop import EvolutionOrchestrator
from neurova.evolution.tool_lifecycle import ToolLifecycleManager, ToolLifecycleState


class TestLifecycleFiltering:
    """测试工具选择时的生命周期过滤"""
    
    def test_archived_tools_filtered_from_selection(self):
        """归档工具应从推荐列表中过滤"""
        # Arrange
        lifecycle = ToolLifecycleManager()
        lifecycle.register_tool("active_tool")
        lifecycle.register_tool("archived_tool")
        
        # 手动设置归档状态
        lifecycle._entries["archived_tool"].state = ToolLifecycleState.ARCHIVED
        
        orchestrator = EvolutionOrchestrator(tool_lifecycle=lifecycle)
        
        # Act
        result = orchestrator.on_before_tool_selection(
            tools=["active_tool", "archived_tool"],
            context="test query"
        )
        
        # Assert
        assert "active_tool" in result["ranking"]
        assert "archived_tool" not in result["ranking"]
        assert "archived_tool" in result["filtered"]
    
    def test_frozen_tools_filtered_from_selection(self):
        """冻结工具应从推荐列表中过滤"""
        # Arrange
        lifecycle = ToolLifecycleManager()
        lifecycle.register_tool("active_tool")
        lifecycle.register_tool("frozen_tool")
        
        lifecycle._entries["frozen_tool"].state = ToolLifecycleState.FROZEN
        
        orchestrator = EvolutionOrchestrator(tool_lifecycle=lifecycle)
        
        # Act
        result = orchestrator.on_before_tool_selection(
            tools=["active_tool", "frozen_tool"],
            context="test query"
        )
        
        # Assert
        assert "active_tool" in result["ranking"]
        assert "frozen_tool" not in result["ranking"]
        assert "frozen_tool" in result["filtered"]
    
    def test_degraded_tools_kept_but_downweighted(self):
        """降级工具应保留在列表中但降权30%"""
        # Arrange
        lifecycle = ToolLifecycleManager()
        lifecycle.register_tool("active_tool")
        lifecycle.register_tool("degraded_tool")
        
        lifecycle._entries["degraded_tool"].state = ToolLifecycleState.DEGRADED
        
        orchestrator = EvolutionOrchestrator(tool_lifecycle=lifecycle)
        
        # 注册工具权重
        orchestrator.tool_weights.register_tool("active_tool", base_weight=1.0)
        orchestrator.tool_weights.register_tool("degraded_tool", base_weight=1.0)
        
        # Act
        result = orchestrator.on_before_tool_selection(
            tools=["active_tool", "degraded_tool"],
            context="test query"
        )
        
        # Assert
        assert "active_tool" in result["ranking"]
        assert "degraded_tool" in result["ranking"]
        assert "degraded_tool" not in result["filtered"]
        
        # 降级工具权重应降低30%
        assert result["weights"]["degraded_tool"] == pytest.approx(0.7, abs=0.01)
        assert result["weights"]["active_tool"] == pytest.approx(1.0, abs=0.01)


class TestLifecycleStateUpdate:
    """测试工具执行后生命周期状态更新"""
    
    def test_tool_execution_updates_lifecycle(self):
        """工具执行后应更新生命周期状态"""
        # Arrange
        lifecycle = ToolLifecycleManager()
        orchestrator = EvolutionOrchestrator(tool_lifecycle=lifecycle)
        
        # 注册工具
        orchestrator.register_tools(["test_tool"])
        
        # Act
        orchestrator.on_after_tool_execution(
            tool_name="test_tool",
            success=True,
            context="test context"
        )
        
        # Assert - 验证touch被调用（通过total_calls增加）
        entry = lifecycle._entries.get("test_tool")
        assert entry is not None
        assert entry.total_calls == 1
    
    def test_failed_execution_still_updates_lifecycle(self):
        """工具执行失败也应更新生命周期状态（记录使用）"""
        # Arrange
        lifecycle = ToolLifecycleManager()
        orchestrator = EvolutionOrchestrator(tool_lifecycle=lifecycle)
        
        orchestrator.register_tools(["test_tool"])
        
        # Act
        orchestrator.on_after_tool_execution(
            tool_name="test_tool",
            success=False,
            context="test context"
        )
        
        # Assert
        entry = lifecycle._entries.get("test_tool")
        assert entry is not None
        assert entry.total_calls == 1  # 即使失败也记录使用


class TestLifecycleStatistics:
    """测试统计报告包含生命周期信息"""
    
    def test_statistics_includes_lifecycle(self):
        """统计报告应包含生命周期信息"""
        # Arrange
        lifecycle = ToolLifecycleManager()
        orchestrator = EvolutionOrchestrator(tool_lifecycle=lifecycle)
        
        # register_tools 现在同时注册到权重和生命周期
        orchestrator.register_tools(["tool_a", "tool_b"])
        
        # 设置不同状态
        lifecycle._entries["tool_b"].state = ToolLifecycleState.DEGRADED
        
        # Act
        stats = orchestrator.get_statistics()
        
        # Assert
        assert "lifecycle" in stats
        assert "active" in stats["lifecycle"]
        assert "degraded" in stats["lifecycle"]
        assert stats["lifecycle"]["active"] == 1
        assert stats["lifecycle"]["degraded"] == 1
    
    def test_tool_stats_include_lifecycle_state(self):
        """工具统计应包含生命周期状态"""
        # Arrange
        lifecycle = ToolLifecycleManager()
        orchestrator = EvolutionOrchestrator(tool_lifecycle=lifecycle)
        
        orchestrator.register_tools(["test_tool"])
        
        # Act
        stats = orchestrator.get_statistics()
        
        # Assert
        assert "test_tool" in stats["tools"]
        assert stats["tools"]["test_tool"]["lifecycle_state"] == "active"


class TestLifecycleEvaluation:
    """测试生命周期评估"""
    
    def test_maybe_evaluate_lifecycle_respects_interval(self):
        """生命周期评估应遵守间隔时间"""
        # Arrange
        lifecycle = ToolLifecycleManager()
        orchestrator = EvolutionOrchestrator(tool_lifecycle=lifecycle)
        
        # 设置上次评估时间为刚刚
        orchestrator._last_lifecycle_eval = time.time()
        
        # Mock evaluate方法
        lifecycle.evaluate = Mock()
        
        # Act - 调用时不应触发评估（间隔太短）
        orchestrator._maybe_evaluate_lifecycle()
        
        # Assert
        lifecycle.evaluate.assert_not_called()
    
    def test_maybe_evaluate_lifecycle_triggers_after_interval(self):
        """超过间隔时间应触发生命周期评估"""
        # Arrange
        lifecycle = ToolLifecycleManager()
        orchestrator = EvolutionOrchestrator(tool_lifecycle=lifecycle)
        
        # 设置上次评估时间为很久以前
        orchestrator._last_lifecycle_eval = time.time() - 7200  # 2小时前
        
        # Mock evaluate和apply_decay
        lifecycle.evaluate = Mock()
        lifecycle.apply_decay = Mock(return_value={})
        lifecycle.get_lifecycle_report = Mock(return_value={
            "total": 0, "active": 0, "degraded": 0,
            "archived": 0, "frozen": 0
        })
        
        # Act
        orchestrator._maybe_evaluate_lifecycle()
        
        # Assert
        lifecycle.evaluate.assert_called_once()
        lifecycle.apply_decay.assert_called_once()


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
