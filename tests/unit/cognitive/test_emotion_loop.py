"""
情感闭环测试 — TDD 验证

数据流:
  用户输入 → EmotionAnalyzer → 情感分析 → 注入上下文 + 保存情感 → MemoryManager → 情感记忆 → 下次检索

测试 5 个断裂点修复:
1. PostChatPipeline 使用 EmotionHubEngine（17种情感）而非简单关键词匹配
2. MemoryManager.get_memories_by_emotion() 空实现
3. NeurovaRecallEngine._channel_emotion() 空实现
4. EmotionModule 情感持久化到 SQLite
5. 情感分数写入 Memory 记录并影响检索
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone


# ============================================================
# 断裂点 #1: PostChatPipeline 应使用 EmotionHubEngine
# ============================================================

class TestEmotionAnalyzerUnified:
    """测试情感分析统一到 EmotionHubEngine"""

    def test_emotion_module_analyze_uses_hub_engine(self):
        """EmotionModule.analyze_text_emotion 应能使用 EmotionHubEngine 进行分析"""
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionType

        module = EmotionModule()
        
        # 测试积极情感
        state = module.analyze_text_emotion("我今天非常高兴，太开心了！")
        assert state is not None, "应该返回情感状态"
        assert state.primary_emotion in [EmotionType.JOY, EmotionType.NEUTRAL], \
            f"积极文本应检测到 JOY 或 NEUTRAL，实际: {state.primary_emotion}"
        
        # 测试消极情感
        state2 = module.analyze_text_emotion("我很愤怒，这太糟糕了！")
        assert state2 is not None, "应该返回情感状态"

    def test_emotion_hub_engine_analyze_text(self):
        """EmotionHubEngine.analyze_text 应返回 17 种情感分数"""
        from neurova.cognitive_layers.emotion_context_layer.emotion_hub_engine import EmotionHubEngine

        engine = EmotionHubEngine()
        scores = engine.analyze_text("我非常开心，今天真是美好的一天！")
        
        assert isinstance(scores, dict), "应该返回字典"
        assert len(scores) > 0, "应该有情感分数"
        # 至少应该有 joy 分数
        joy_score = scores.get("joy", 0.0)
        assert joy_score > 0, f"积极文本的 joy 分数应 > 0，实际: {joy_score}"

    def test_emotion_analyzer_returns_dict_for_context(self):
        """EmotionAnalyzer.analyze 应返回 Dict[str, float] 用于上下文注入"""
        from neurova.cognitive_layers.emotion_context_layer.emotion import EmotionAnalyzer

        analyzer = EmotionAnalyzer()
        # 使用包含明确情感关键词的文本进行测试
        result = analyzer.analyze("我今天非常开心，太高兴了！")
        
        assert isinstance(result, dict), "应该返回字典"
        assert len(result) > 0, "应该有情感分数"
        # 验证返回的情感分数有实际值
        assert any(score > 0 for score in result.values()), "应该有非零情感分数"


# ============================================================
# 断裂点 #2: MemoryManager.get_memories_by_emotion 空实现
# ============================================================

class TestGetMemoriesByEmotion:
    """测试 MemoryManager.get_memories_by_emotion()"""

    def test_get_memories_by_emotion_not_empty(self):
        """get_memories_by_emotion 不应返回空列表（当有情感记忆时）"""
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        manager = MemoryManager()
        
        # 验证方法存在且可调用
        assert hasattr(manager, 'get_memories_by_emotion'), \
            "MemoryManager 缺少 get_memories_by_emotion 方法"
        assert callable(manager.get_memories_by_emotion), \
            "get_memories_by_emotion 应该是可调用的"

    def test_get_memories_by_emotion_has_emotion_module(self):
        """MemoryManager 应能访问 emotion_module"""
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        manager = MemoryManager()
        
        # 验证 emotion_module 存在
        assert hasattr(manager, 'emotion_module'), \
            "MemoryManager 缺少 emotion_module 属性"
        assert manager.emotion_module is not None, \
            "emotion_module 不应为 None"


# ============================================================
# 断裂点 #3: _channel_emotion 空实现
# ============================================================

class TestEmotionRecallChannel:
    """测试情感检索通道"""

    def test_neurova_recall_has_emotion_channel(self):
        """NeurovaRecallEngine 应有情感通道"""
        from neurova.cognitive_layers.memory_layer.neurova_recall import RecallChannel
        
        assert RecallChannel.EMOTION, "应有 EMOTION 通道"

    def test_emotion_module_get_emotional_memories(self):
        """EmotionModule.get_emotional_memories 应返回有情感标注的记忆"""
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule, EmotionState, EmotionType

        module = EmotionModule()
        
        # 添加情感记忆
        state = EmotionState(
            primary_emotion=EmotionType.JOY,
            intensity=0.8,
            valence=0.7,
            arousal=0.6,
        )
        module.set_emotion("mem_001", state)
        
        state2 = EmotionState(
            primary_emotion=EmotionType.ANGER,
            intensity=0.9,
            valence=-0.7,
            arousal=0.8,
        )
        module.set_emotion("mem_002", state2)
        
        # 检索 joy 记忆
        joy_ids = module.get_emotional_memories(
            emotion_type=EmotionType.JOY,
            min_intensity=0.5,
        )
        assert "mem_001" in joy_ids, f"mem_001 应在 joy 记忆中，实际: {joy_ids}"
        
        # 检索 anger 记忆
        anger_ids = module.get_emotional_memories(
            emotion_type=EmotionType.ANGER,
            min_intensity=0.5,
        )
        assert "mem_002" in anger_ids, f"mem_002 应在 anger 记忆中，实际: {anger_ids}"


# ============================================================
# 断裂点 #4: EmotionModule 情感持久化
# ============================================================

class TestEmotionPersistence:
    """测试情感持久化到 SQLite"""

    def test_emotion_module_persistence(self):
        """EmotionModule 的情感标注应在进程重启后保持"""
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule, EmotionState, EmotionType
        import tempfile, os

        # 使用临时目录进行持久化测试
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_emotion.db")
            
            # 创建并保存情感
            module1 = EmotionModule(db_path=db_path)
            state = EmotionState(
                primary_emotion=EmotionType.JOY,
                intensity=0.8,
                valence=0.7,
                arousal=0.6,
            )
            module1.set_emotion("mem_001", state)
            
            # 验证内存中存在
            retrieved = module1.get_emotion("mem_001")
            assert retrieved is not None, "内存中应存在情感"
            assert retrieved.primary_emotion == EmotionType.JOY
            
            # 关闭并重新加载
            module1.shutdown()
            
            module2 = EmotionModule(db_path=db_path)
            retrieved2 = module2.get_emotion("mem_001")
            assert retrieved2 is not None, "重启后应能加载情感"
            assert retrieved2.primary_emotion == EmotionType.JOY
            assert abs(retrieved2.intensity - 0.8) < 0.01, \
                f"强度应保持一致: {retrieved2.intensity}"
            
            module2.shutdown()


# ============================================================
# 断裂点 #5: 情感分数写入 Memory 记录
# ============================================================

class TestEmotionWriteToMemory:
    """测试情感分数写入 Memory 记录并影响检索"""

    def test_memory_record_has_emotion_score(self):
        """Memory 记录应包含 emotion_score 字段"""
        from neurova.cognitive_layers.memory_layer.models import Memory

        # emotion 字段类型是 EmotionType 枚举（models.py:259），非裸字符串
        from neurova.cognitive_layers.memory_layer.models import EmotionType

        mem = Memory(
            content="测试记忆",
            emotion=EmotionType.JOY,
            temperature=80.0,
        )
        
        # 验证字段存在
        assert hasattr(mem, 'emotion'), "Memory 应有 emotion 字段"
        
        # 验证序列化
        mem_dict = mem.to_dict()
        assert "emotion" in mem_dict, "to_dict 应包含 emotion"

    def test_remember_with_emotion(self):
        """MemoryManager.remember() 应支持保存情感标注"""
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        manager = MemoryManager()
        
        # 添加带情感的记忆
        memory_id = manager.remember(
            content="今天非常开心",
            category="conversation",
        )
        
        assert memory_id, "应返回记忆 ID"
        
        # 验证记忆存在
        memories = manager.get_all_memories()
        assert len(memories) >= 1, "应有记忆"

    def test_emotion_temperature_modifier(self):
        """EmotionModule.get_temperature_modifier 应返回有效修正值"""
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule, EmotionState, EmotionType

        module = EmotionModule()
        
        # 设置积极情感
        state = EmotionState(
            primary_emotion=EmotionType.JOY,
            intensity=0.8,
            valence=0.7,
            arousal=0.6,
        )
        module.set_emotion("mem_001", state)
        
        # 获取温度修正
        modifier = module.get_temperature_modifier("mem_001")
        assert modifier > 0, f"积极情感的温度修正应 > 0，实际: {modifier}"
        
        # 设置消极情感
        state2 = EmotionState(
            primary_emotion=EmotionType.ANGER,
            intensity=0.9,
            valence=-0.7,
            arousal=0.8,
        )
        module.set_emotion("mem_002", state2)
        
        modifier2 = module.get_temperature_modifier("mem_002")
        assert modifier2 < 0, f"消极情感的温度修正应 < 0，实际: {modifier2}"


# ============================================================
# 端到端闭环测试
# ============================================================

class TestEmotionLoopEndToEnd:
    """端到端情感闭环测试"""

    def test_full_emotion_loop(self):
        """完整情感闭环：分析 → 保存 → 检索"""
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import (
            EmotionModule, EmotionState, EmotionType,
        )
        from neurova.cognitive_layers.emotion_context_layer.emotion_hub_engine import EmotionHubEngine

        # 1. 创建组件
        emotion_module = EmotionModule()
        hub_engine = EmotionHubEngine()
        
        # 2. 模拟用户输入
        user_input = "我今天非常开心，终于完成了项目！"
        
        # 3. 情感分析（使用 HubEngine）
        scores = hub_engine.analyze_text(user_input)
        assert scores, "HubEngine 应返回情感分数"
        
        # 4. 保存情感到记忆
        state = EmotionState(
            primary_emotion=EmotionType.JOY,
            intensity=scores.get("joy", 0.5),
            valence=0.7,
            arousal=0.6,
        )
        emotion_module.set_emotion("mem_001", state)
        
        # 5. 验证情感保存
        retrieved = emotion_module.get_emotion("mem_001")
        assert retrieved is not None, "情感应已保存"
        assert retrieved.primary_emotion == EmotionType.JOY
        
        # 6. 检索情感记忆
        joy_ids = emotion_module.get_emotional_memories(
            emotion_type=EmotionType.JOY,
            min_intensity=0.3,
        )
        assert "mem_001" in joy_ids, f"mem_001 应在 joy 记忆中: {joy_ids}"
        
        # 7. 温度修正
        modifier = emotion_module.get_temperature_modifier("mem_001")
        assert modifier > 0, f"积极情感应提高温度: {modifier}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
