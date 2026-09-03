"""
进化系统门面单元测试

测试EvolutionFacade的基本功能
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from neurova.evolution.evolution_facade import (
    EvolutionFacade,
    EvolutionResult,
    get_evolution_facade,
    reset_evolution_facade,
)


class TestEvolutionResult:
    """EvolutionResult测试"""
    
    def test_init(self):
        """测试初始化"""
        result = EvolutionResult(
            success=True,
            data={"weight": 0.8},
            metadata={"tool": "test"},
        )
        assert result.success is True
        assert result.data["weight"] == 0.8
    
    def test_to_dict(self):
        """测试转换为字典"""
        result = EvolutionResult(success=True)
        d = result.to_dict()
        assert "success" in d
        assert "data" in d


class TestEvolutionFacade:
    """EvolutionFacade测试"""
    
    def test_init(self):
        """测试初始化"""
        facade = EvolutionFacade()
        assert facade is not None
    
    def test_get_tool_weight_with_no_orchestrator(self):
        """测试无orchestrator时获取工具权重"""
        facade = EvolutionFacade()
        weight = facade.get_tool_weight("test_tool")
        assert weight == 1.0
    
    def test_update_tool_weight_with_no_orchestrator(self):
        """测试无orchestrator时更新工具权重"""
        facade = EvolutionFacade()
        # 不应抛出异常
        facade.update_tool_weight("test_tool", success=True)
    
    def test_rank_tools(self):
        """测试工具排序"""
        facade = EvolutionFacade()
        tools = ["tool_a", "tool_b", "tool_c"]
        result = facade.rank_tools(tools)
        assert len(result) == 3
        assert all(t in tools for t in result)
    
    def test_rank_tools_empty(self):
        """测试空工具列表排序"""
        facade = EvolutionFacade()
        result = facade.rank_tools([])
        assert result == []
    
    def test_get_tool_lifecycle_state(self):
        """测试获取工具生命周期状态"""
        facade = EvolutionFacade()
        state = facade.get_tool_lifecycle_state("test_tool")
        assert state == "active"
    
    def test_touch_tool(self):
        """测试更新工具生命周期"""
        facade = EvolutionFacade()
        # 不应抛出异常
        facade.touch_tool("test_tool")
    
    def test_select_tools(self):
        """测试工具选择"""
        facade = EvolutionFacade()
        result = facade.select_tools(["tool_a", "tool_b", "tool_c"], "test context")
        assert "selected" in result
        assert len(result["selected"]) <= 3
    
    def test_record_experience(self):
        """测试记录经验"""
        facade = EvolutionFacade()
        result = facade.record_experience("test", "task", ["tool"], True)
        assert result["success"] is False  # 无orchestrator
    
    def test_add_tool_sequence(self):
        """测试添加工具序列"""
        facade = EvolutionFacade()
        # 不应抛出异常
        facade.add_tool_sequence(["tool_a", "tool_b"], "context")
    
    def test_get_frequent_patterns(self):
        """测试获取频繁模式"""
        facade = EvolutionFacade()
        result = facade.get_frequent_patterns()
        assert result == []
    
    def test_synthesize_tools(self):
        """测试工具合成"""
        facade = EvolutionFacade()
        result = facade.synthesize_tools()
        assert result == []
    
    def test_get_statistics(self):
        """测试获取统计信息"""
        facade = EvolutionFacade()
        result = facade.get_statistics()
        assert result == {}
    
    def test_on_after_tool_execution_compat(self):
        """测试兼容旧接口"""
        facade = EvolutionFacade()
        # 不应抛出异常
        facade.on_after_tool_execution("test_tool", success=True, latency=0.1)
    
    def test_on_experience_recorded_compat(self):
        """测试兼容旧接口"""
        facade = EvolutionFacade()
        result = facade.on_experience_recorded_compat("test", "task", ["tool"], True)
        assert result["success"] is False  # 无orchestrator


class TestEvolutionFacadeSingleton:
    """EvolutionFacade单例测试"""
    
    def test_singleton(self):
        """测试单例模式"""
        reset_evolution_facade()
        
        facade1 = get_evolution_facade(Mock())
        facade2 = get_evolution_facade()
        
        assert facade1 is facade2
        
        reset_evolution_facade()
