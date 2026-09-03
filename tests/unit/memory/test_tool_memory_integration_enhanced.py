"""
ToolMemoryIntegration 增强功能测试

测试内容：
1. 动态置信度阈值计算
2. 生命周期集成
3. 工具废弃检测
"""
import sys
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
from unittest.mock import Mock, MagicMock
from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
from neurova.evolution.closed_loop import AdaptiveToolWeights, ToolWeight
from neurova.evolution.tool_lifecycle import ToolLifecycleManager, ToolLifecycleState


class TestDynamicThreshold:
    """测试动态置信度阈值计算"""
    
    def test_no_tool_weights_returns_base_threshold(self):
        """无工具权重时返回基础阈值"""
        # Arrange
        memory_layer = Mock()
        tool_memory = ToolMemoryIntegration(
            memory_layer=memory_layer,
            confidence_threshold=0.8,
        )
        
        # Act
        threshold = tool_memory._get_dynamic_threshold("browser_click")
        
        # Assert
        assert threshold == 0.8
    
    def test_high_weight_lowers_threshold(self):
        """高权重工具降低阈值（更容易自动执行）"""
        # Arrange
        memory_layer = Mock()
        tool_weights = AdaptiveToolWeights()
        tool_weights.register_tool("browser_click", base_weight=2.5)
        
        tool_memory = ToolMemoryIntegration(
            memory_layer=memory_layer,
            confidence_threshold=0.8,
            tool_weights=tool_weights,
        )
        
        # Act
        threshold = tool_memory._get_dynamic_threshold("browser_click")
        
        # Assert
        # 权重2.5时：threshold = 0.8 / sqrt(2.5) ≈ 0.51
        assert threshold < 0.8
        assert threshold >= 0.3  # 下限
    
    def test_low_weight_raises_threshold(self):
        """低权重工具提高阈值（更难自动执行）"""
        # Arrange
        memory_layer = Mock()
        tool_weights = AdaptiveToolWeights()
        tool_weights.register_tool("screenshot", base_weight=0.3)
        
        tool_memory = ToolMemoryIntegration(
            memory_layer=memory_layer,
            confidence_threshold=0.8,
            tool_weights=tool_weights,
        )
        
        # Act
        threshold = tool_memory._get_dynamic_threshold("screenshot")
        
        # Assert
        # 权重0.3时：threshold = 0.8 / sqrt(0.3) ≈ 1.46，但限制在1.0
        assert threshold > 0.8
        assert threshold <= 1.0  # 上限
    
    def test_unknown_tool_returns_base_threshold(self):
        """未知工具返回基础阈值"""
        # Arrange
        memory_layer = Mock()
        tool_weights = AdaptiveToolWeights()
        
        tool_memory = ToolMemoryIntegration(
            memory_layer=memory_layer,
            confidence_threshold=0.8,
            tool_weights=tool_weights,
        )
        
        # Act
        threshold = tool_memory._get_dynamic_threshold("unknown_tool")
        
        # Assert
        assert threshold == 0.8
    
    def test_threshold_bounds(self):
        """阈值限制在0.3-1.0范围内"""
        # Arrange
        memory_layer = Mock()
        tool_weights = AdaptiveToolWeights()
        
        # 极高权重
        tool_weights.register_tool("high_weight", base_weight=10.0)
        # 极低权重
        tool_weights.register_tool("low_weight", base_weight=0.01)
        
        tool_memory = ToolMemoryIntegration(
            memory_layer=memory_layer,
            confidence_threshold=0.8,
            tool_weights=tool_weights,
        )
        
        # Act & Assert
        high_threshold = tool_memory._get_dynamic_threshold("high_weight")
        low_threshold = tool_memory._get_dynamic_threshold("low_weight")
        
        assert high_threshold >= 0.3
        assert high_threshold <= 1.0
        assert low_threshold >= 0.3
        assert low_threshold <= 1.0


class TestCheckToolMemoryWithDynamicThreshold:
    """测试 check_tool_memory 使用动态阈值"""
    
    def test_high_weight_tool_auto_executes(self):
        """高权重工具更容易自动执行"""
        # Arrange
        memory_layer = Mock()
        muscle_memory = Mock()
        tool_weights = AdaptiveToolWeights()
        tool_weights.register_tool("browser_click", base_weight=2.5)
        
        # 模拟肌肉记忆匹配，置信度0.75
        mock_item = MagicMock()
        mock_item.tool_name = "browser_click"
        mock_item.parameters = {}
        mock_item.metadata = {"tool_source": "cli"}
        mock_item.level = MagicMock()
        mock_item.level.value = "l2"
        muscle_memory.match_by_query.return_value = [(mock_item, 0.75)]
        
        tool_memory = ToolMemoryIntegration(
            memory_layer=memory_layer,
            muscle_memory=muscle_memory,
            confidence_threshold=0.8,
            tool_weights=tool_weights,
        )
        
        # Act
        tool_info, decision = tool_memory.check_tool_memory("test query")
        
        # Assert
        # 权重2.5时，动态阈值≈0.51，置信度0.75 > 0.51，应该自动执行
        assert decision == "auto_execute"
        assert tool_info["tool_name"] == "browser_click"
        assert "dynamic_threshold" in tool_info
    
    def test_low_weight_tool_asks_user(self):
        """低权重工具更难自动执行"""
        # Arrange
        memory_layer = Mock()
        muscle_memory = Mock()
        tool_weights = AdaptiveToolWeights()
        tool_weights.register_tool("screenshot", base_weight=0.3)
        
        # 模拟肌肉记忆匹配，置信度0.85
        mock_item = MagicMock()
        mock_item.tool_name = "screenshot"
        mock_item.parameters = {}
        mock_item.metadata = {"tool_source": "cli"}
        mock_item.level = MagicMock()
        mock_item.level.value = "l2"
        muscle_memory.match_by_query.return_value = [(mock_item, 0.85)]
        
        tool_memory = ToolMemoryIntegration(
            memory_layer=memory_layer,
            muscle_memory=muscle_memory,
            confidence_threshold=0.8,
            tool_weights=tool_weights,
        )
        
        # Act
        tool_info, decision = tool_memory.check_tool_memory("test query")
        
        # Assert
        # 权重0.3时，动态阈值≈1.0（被限制），置信度0.85 < 1.0，应该建议
        assert decision == "suggest"
        assert tool_info["tool_name"] == "screenshot"


class TestLifecycleIntegration:
    """测试生命周期集成"""
    
    def test_should_demote_deprecated_tool(self):
        """已废弃工具应该从肌肉记忆中降级"""
        # Arrange
        memory_layer = Mock()
        tool_lifecycle = Mock()
        
        # 模拟工具已归档
        tool_lifecycle.get_state.return_value = ToolLifecycleState.ARCHIVED
        
        tool_memory = ToolMemoryIntegration(
            memory_layer=memory_layer,
            tool_lifecycle=tool_lifecycle,
        )
        
        # Act
        should_demote = tool_memory._should_demote_from_muscle_memory("old_tool")
        
        # Assert
        assert should_demote is True
    
    def test_should_demote_degraded_tool(self):
        """已降级工具也应该从肌肉记忆中降级"""
        # Arrange
        memory_layer = Mock()
        tool_lifecycle = Mock()
        
        # 模拟工具已降级
        tool_lifecycle.get_state.return_value = ToolLifecycleState.DEGRADED
        
        tool_memory = ToolMemoryIntegration(
            memory_layer=memory_layer,
            tool_lifecycle=tool_lifecycle,
        )
        
        # Act
        should_demote = tool_memory._should_demote_from_muscle_memory("degraded_tool")
        
        # Assert
        assert should_demote is True
    
    def test_should_not_demote_active_tool(self):
        """活跃工具不应该从肌肉记忆中降级"""
        # Arrange
        memory_layer = Mock()
        tool_lifecycle = Mock()
        
        # 模拟工具活跃
        tool_lifecycle.get_state.return_value = ToolLifecycleState.ACTIVE
        
        tool_memory = ToolMemoryIntegration(
            memory_layer=memory_layer,
            tool_lifecycle=tool_lifecycle,
        )
        
        # Act
        should_demote = tool_memory._should_demote_from_muscle_memory("active_tool")
        
        # Assert
        assert should_demote is False
    
    def test_cleanup_deprecated_tools(self):
        """清理已废弃工具的肌肉记忆"""
        # Arrange
        memory_layer = Mock()
        muscle_memory = Mock()
        tool_lifecycle = Mock()
        
        # 使用 MagicMock 字典，使 pop() 可追踪
        # Bug AUDIT2-010 修复: 属性名从 l1_items/l2_items/l3_items 改为 _l1/_l2/_l3
        deprecated_item = Mock(tool_name="deprecated_tool")
        active_item = Mock(tool_name="active_tool")
        
        l1_items = MagicMock()
        l1_items.items.return_value = [("item1", deprecated_item)]
        l1_items.pop.return_value = deprecated_item  # pop(item_id, None) 形式
        
        l2_items = MagicMock()
        l2_items.items.return_value = []
        
        l3_items = MagicMock()
        l3_items.items.return_value = [("item2", active_item)]
        
        muscle_memory._l1 = l1_items
        muscle_memory._l2 = l2_items
        muscle_memory._l3 = l3_items
        
        # 模拟工具状态
        def get_state(tool_name):
            if tool_name == "deprecated_tool":
                return ToolLifecycleState.ARCHIVED
            return ToolLifecycleState.ACTIVE
        
        tool_lifecycle.get_state.side_effect = get_state
        
        tool_memory = ToolMemoryIntegration(
            memory_layer=memory_layer,
            muscle_memory=muscle_memory,
            tool_lifecycle=tool_lifecycle,
        )
        
        # Act
        cleaned_count = tool_memory._cleanup_deprecated_tools()
        
        # Assert
        assert cleaned_count == 1
        l1_items.pop.assert_called_once_with("item1", None)


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
