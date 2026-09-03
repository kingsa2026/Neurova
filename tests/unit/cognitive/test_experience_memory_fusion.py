"""
经验记忆融合器测试

TDD: 先写测试，再实现
"""

import pytest
from neurova.cognitive_layers.memory_layer.experience_memory_fusion import ExperienceMemoryFusion


class TestExperienceMemoryFusion:
    """ExperienceMemoryFusion 测试"""
    
    def test_init(self):
        """测试初始化"""
        fusion = ExperienceMemoryFusion()
        assert fusion is not None
    
    def test_fuse_tool_with_graph(self):
        """测试工具经验与图谱融合"""
        fusion = ExperienceMemoryFusion()
        
        tool_result = {
            "tool_name": "db_check",
            "success": True,
            "execution_time": 0.5,
            "problem_text": "数据库连接失败",
        }
        
        graph_context = {
            "related_entities": ["数据库", "连接池"],
            "causal_chains": ["数据库故障→API异常"],
        }
        
        result = fusion.fuse(tool_result, graph_context)
        
        assert "tool_name" in result
        assert "graph_context" in result
        assert "confidence" in result
    
    def test_fuse_without_graph(self):
        """测试无图谱上下文时的融合"""
        fusion = ExperienceMemoryFusion()
        
        tool_result = {
            "tool_name": "log_analyzer",
            "success": True,
            "execution_time": 0.3,
        }
        
        result = fusion.fuse(tool_result, {})
        
        assert result["tool_name"] == "log_analyzer"
        assert result["confidence"] > 0
    
    def test_calculate_fusion_confidence(self):
        """测试融合置信度计算"""
        fusion = ExperienceMemoryFusion()
        
        # 成功的工具 + 相关图谱
        confidence = fusion._calculate_confidence(
            success=True,
            has_graph_context=True,
            execution_time=0.5,
        )
        assert confidence > 0.7
        
        # 失败的工具（没有图谱上下文和快速执行的加分）
        confidence = fusion._calculate_confidence(
            success=False,
            has_graph_context=False,
            execution_time=2.0,
        )
        assert confidence == 0.5  # 只有基础置信度
    
    def test_get_fused_memories(self):
        """测试获取融合记忆"""
        fusion = ExperienceMemoryFusion()
        
        # 添加一些融合结果
        fusion._fused_memories = [
            {"tool_name": "db_check", "confidence": 0.9, "graph_context": {}},
            {"tool_name": "log_analyzer", "confidence": 0.7, "graph_context": {}},
        ]
        
        memories = fusion.get_fused_memories(limit=10)
        assert len(memories) == 2
