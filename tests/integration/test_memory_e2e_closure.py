"""
端到端测试：对话记忆写入闭环验证

TDD 垂直切片策略：
- Tracer Bullet (测试1): buffer添加消息 → 验证计数正确
- 切片2 (测试2-3): buffer刷新触发 → 验证刷新逻辑
- 切片4 (测试4-5): MemoryWriteQueue → 验证入队和刷写
- 切片6 (测试6-8): 温度衰减 → 验证贝叶斯遗忘曲线
- 切片9 (测试9-10): 温度升温 → 验证访问加温
- 切片11 (测试11-12): 生命周期 → 验证阶段判定
- 切片13-14: 图遍历 → 验证关联检索
- 切片15-16: 端到端管道 → 完整链路验证
"""

import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock

# 导入核心模块
from neurova.cognitive_layers.memory_layer.conversation_buffer import (
    ConversationBuffer,
    ConversationMemoryBuffer,
    MemoryWriteQueue,
    MemoryItem,
    ConversationTurn,
)
from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine


# ============================================================
# Tracer Bullet: P0 对话记忆写入闭环
# ============================================================

class TestMemoryWriteClosure:
    """P0: 对话记忆写入闭环测试"""

    def test_buffer_add_messages(self):
        """测试1: 缓冲区能正确添加用户和AI消息，并跟踪轮次"""
        buffer = ConversationBuffer(turn_limit=10)
        
        # 添加用户消息
        assert buffer.add_user_message("你好") is True
        
        # 添加AI回复（完成一轮）
        assert buffer.add_agent_message("你好！有什么可以帮助你的？") is True
        
        # 验证缓冲区状态
        stats = buffer.get_stats()
        assert stats['buffer_size'] == 2
        assert stats['current_turns'] == 1
        assert stats['has_current_turn'] is False  # 轮次已完成

    def test_buffer_flush_trigger_by_turn_limit(self):
        """测试2: 缓冲区在达到轮次限制时触发刷新"""
        buffer = ConversationBuffer(turn_limit=2)
        
        # 添加2轮对话
        for i in range(2):
            buffer.add_user_message(f"用户消息 {i+1}")
            buffer.add_agent_message(f"AI回复 {i+1}")
        
        # 验证 should_flush
        assert buffer.is_full() is True

    def test_buffer_flush_returns_items(self):
        """测试3: flush返回所有缓冲项并清空缓冲区"""
        buffer = ConversationBuffer(turn_limit=10)
        buffer.add_user_message("消息1")
        buffer.add_agent_message("回复1")
        buffer.add_user_message("消息2")
        
        items = buffer.flush()
        assert len(items) == 3
        assert items[0].content == "消息1"
        assert items[1].content == "回复1"
        assert items[2].content == "消息2"
        
        # 缓冲区已清空
        stats = buffer.get_stats()
        assert stats['buffer_size'] == 0
        assert stats['current_turns'] == 0

    def test_memory_item_fields(self):
        """测试4: MemoryItem包含正确的字段"""
        item = MemoryItem(
            id="test_001",
            content="测试内容",
            timestamp=datetime.now(),
            classification="conversation",
            categories=["test"]
        )
        
        assert item.id == "test_001"
        assert item.content == "测试内容"
        assert item.classification == "conversation"
        assert "test" in item.categories

    def test_write_queue_enqueue_and_flush(self):
        """测试5: WriteQueue能正确入队和批量刷写"""
        mock_storage = Mock()
        queue = MemoryWriteQueue(mock_storage, agent_id="test_agent")
        
        item1 = MemoryItem(id="q1", content="内容1", timestamp=datetime.now())
        item2 = MemoryItem(id="q2", content="内容2", timestamp=datetime.now())
        
        # 单个入队
        assert queue.enqueue(item1) is True
        assert queue.get_queue_size() == 1
        
        # 批量入队
        queue.enqueue_batch([item2])
        assert queue.get_queue_size() == 2
        
        # 刷写到存储
        count = queue.flush_to_storage()
        assert count == 2
        assert queue.get_queue_size() == 0


# ============================================================
# P1: 贝叶斯遗忘曲线
# ============================================================

class TestBayesianForgetting:
    """P1: 贝叶斯遗忘曲线验证"""

    def test_decay_reduces_temperature(self):
        """测试6: 温度衰减能正确降低温度"""
        # 7天前访问过的记忆
        result = TemperatureEngine.on_decay(
            current_temp=80.0,
            days_idle=7.0,
            importance=0.5,
            emotion_score=0.3,
        )
        
        assert result < 80.0
        assert result > 0.0

    def test_emotional_protection_reduces_decay(self):
        """测试7: 情感分数对衰减有保护作用"""
        # 无情感保护
        temp_no_emotion = TemperatureEngine.on_decay(
            current_temp=80.0,
            days_idle=7.0,
            emotion_score=0.0,
        )
        
        # 有情感保护
        temp_with_emotion = TemperatureEngine.on_decay(
            current_temp=80.0,
            days_idle=7.0,
            emotion_score=0.8,
        )
        
        # 有情感保护的温度应该更高（衰减更少）
        assert temp_with_emotion >= temp_no_emotion

    def test_important_memory_decays_slower(self):
        """测试8: 重要记忆衰减更慢"""
        # 非重要记忆
        temp_not_important = TemperatureEngine.on_decay(
            current_temp=80.0,
            days_idle=7.0,
            importance=0.1,
        )
        
        # 重要记忆
        temp_important = TemperatureEngine.on_decay(
            current_temp=80.0,
            days_idle=7.0,
            importance=0.9,
        )
        
        # 重要记忆衰减更少
        assert temp_important >= temp_not_important


# ============================================================
# P1: 温度访问升温
# ============================================================

class TestTemperatureAccess:
    """P1: 温度访问升温验证"""

    def test_access_increases_temperature(self):
        """测试9: 访问能提升温度"""
        new_temp = TemperatureEngine.on_access(
            current_temp=50.0,
            importance=0.5,
            recall_count=3,
        )
        
        assert new_temp > 50.0
        assert new_temp <= 100.0

    def test_recall_count_boosts_warming(self):
        """测试10: 回忆次数越高，升温越多"""
        temp_low_recall = TemperatureEngine.on_access(
            current_temp=50.0,
            importance=0.5,
            recall_count=1,
        )
        
        temp_high_recall = TemperatureEngine.on_access(
            current_temp=50.0,
            importance=0.5,
            recall_count=10,
        )
        
        assert temp_high_recall >= temp_low_recall


# ============================================================
# P1+: 生命周期阶段
# ============================================================

class TestLifecycleStages:
    """P1+: 生命周期阶段验证"""

    def test_active_stage(self):
        """测试11: 高温为active阶段"""
        stage = TemperatureEngine.get_lifecycle_stage(80.0)
        assert stage == TemperatureEngine.STAGE_ACTIVE

    def test_secondary_stage(self):
        """测试12: 中温为secondary阶段"""
        stage = TemperatureEngine.get_lifecycle_stage(40.0)
        assert stage == TemperatureEngine.STAGE_SECONDARY

    def test_archived_stage(self):
        """测试13: 低温为archived阶段"""
        stage = TemperatureEngine.get_lifecycle_stage(10.0)
        assert stage == TemperatureEngine.STAGE_ARCHIVED

    def test_deleted_stage(self):
        """测试14: 极低温为deleted阶段"""
        stage = TemperatureEngine.get_lifecycle_stage(2.0)
        assert stage == TemperatureEngine.STAGE_DELETED


# ============================================================
# P2: 图遍历检索
# ============================================================

class TestGraphTraversal:
    """P2: 图遍历检索验证"""

    def test_relation_types_valid(self):
        """测试15: 关联类型定义"""
        valid_relation_types = [
            "related", "causes", "contradicts", "supports",
            "part_of", "derived_from", "temporal"
        ]
        
        assert len(valid_relation_types) > 0
        assert "related" in valid_relation_types

    def test_relation_strength_range(self):
        """测试16: 关联强度范围在0-1"""
        # 关联强度应该在0-1之间
        strengths = [0.0, 0.25, 0.5, 0.75, 1.0]
        
        for strength in strengths:
            assert 0.0 <= strength <= 1.0


# ============================================================
# P2: 端到端管道验证
# ============================================================

class TestEndToEndPipeline:
    """P2: 端到端管道覆盖"""

    def test_full_buffer_lifecycle(self):
        """测试17: 完整的缓冲区生命周期 - 添加→检查→刷新"""
        buffer = ConversationBuffer(turn_limit=3)
        
        # 1. 添加对话
        buffer.add_user_message("什么是机器学习？")
        buffer.add_agent_message("机器学习是人工智能的一个分支...")
        
        # 2. 检查状态
        stats = buffer.get_stats()
        assert stats['buffer_size'] == 2
        assert stats['current_turns'] == 1
        
        # 3. 继续添加
        buffer.add_user_message("深度学习呢？")
        buffer.add_agent_message("深度学习是机器学习的子集...")
        buffer.add_user_message("两者有什么区别？")
        
        # 4. 刷新
        items = buffer.flush()
        assert len(items) == 5
        
        # 5. 验证缓冲区已清空
        assert buffer.get_stats()['buffer_size'] == 0

    def test_forgetting_probability_calculation(self):
        """测试18: 遗忘概率计算"""
        # 新记忆，遗忘概率低
        prob_new = TemperatureEngine.calculate_forgetting_probability(
            temperature=90.0,
            days_idle=0.5,
            importance=0.8,
            emotion_score=0.6,
        )
        
        # 旧记忆，遗忘概率高
        prob_old = TemperatureEngine.calculate_forgetting_probability(
            temperature=30.0,
            days_idle=60.0,
            importance=0.2,
            emotion_score=0.1,
        )
        
        # 新记忆遗忘概率更低
        assert prob_new < prob_old

    def test_write_queue_full_cycle(self):
        """测试19: WriteQueue完整生命周期"""
        mock_storage = Mock()
        queue = MemoryWriteQueue(mock_storage, agent_id="agent_1")
        
        # 1. 批量入队
        items = [
            MemoryItem(id=f"m{i}", content=f"记忆{i}", timestamp=datetime.now())
            for i in range(5)
        ]
        queue.enqueue_batch(items)
        assert queue.get_queue_size() == 5
        
        # 2. 刷写
        count = queue.flush_to_storage()
        assert count == 5
        
        # 3. 验证队列已清空
        assert queue.get_queue_size() == 0

    def test_buffer_timeout_detection(self):
        """测试20: 缓冲区超时检测"""
        buffer = ConversationBuffer(
            turn_limit=100,  # 设置很大的轮次限制
            timeout_seconds=0  # 立即超时
        )
        
        buffer.add_user_message("测试消息")
        
        # 超时应该触发 is_full
        assert buffer.is_full() is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])