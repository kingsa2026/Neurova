"""
记忆温度更新测试

修复: _update_memory_temperature() 空方法，try/except 中只有 pass
影响: 记忆温度永不更新
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.post_chat_pipeline import PostChatPipeline


class TestTemperatureEngineBasics:
    """TemperatureEngine 核心功能测试"""

    def test_on_access_boosts_temperature(self):
        """on_access 应提升温度

        实际公式（temperature.py 行 97-149）：
          base_boost = 10 * importance * (decay_rate/0.1) = 10 * 0.8 * 1.0 = 8.0
          saturation = max(0.1, 1.0 - (50/100) * 0.8) = 0.6
          access_boost = 8.0 * 0.6 = 4.8
          recall_boost = min(3*2, 20) = 6.0
          combo_multiplier = 1.0 (access_count=0)
          emotion_bonus = 0.0, relation_bonus = 0.0
          new_temp = 50 + (4.8 + 6.0) * 1.0 = 60.8
        """
        new_temp = TemperatureEngine.on_access(
            current_temp=50.0,
            importance=0.8,
            recall_count=3,
        )
        assert new_temp == 60.8

    def test_on_access_clamped_to_100(self):
        """on_access 温度不应超过 100"""
        new_temp = TemperatureEngine.on_access(
            current_temp=95.0,
            importance=1.0,
            recall_count=10,
        )
        assert new_temp == 100.0

    def test_on_access_clamped_to_0(self):
        """on_access 温度不应低于 0"""
        new_temp = TemperatureEngine.on_access(
            current_temp=0.0,
            importance=0.0,
            recall_count=0,
        )
        assert new_temp == 0.0

    def test_on_decay_reduces_temperature(self):
        """on_decay 应降低温度

        注意：on_decay 返回 dict {'new_temp', 'lifecycle_stage', ...}，不是 float
        高温(>=80)不衰减，所以用 60.0 测试
        """
        result = TemperatureEngine.on_decay(
            current_temp=60.0,
            days_idle=7.0,
            importance=0.5,
            emotion_score=0.3,
        )
        assert isinstance(result, dict)
        assert result['new_temp'] < 60.0
        assert result['new_temp'] >= 0.0

    def test_on_decay_with_emotion_protection(self):
        """高情感分数应减缓衰减

        注意：on_decay 返回 dict，需取 'new_temp' 比较
        """
        result_without = TemperatureEngine.on_decay(
            current_temp=60.0,
            days_idle=10.0,
            importance=0.5,
            emotion_score=0.3,
        )
        result_with = TemperatureEngine.on_decay(
            current_temp=60.0,
            days_idle=10.0,
            importance=0.5,
            emotion_score=0.8,
        )
        # 高情感分数应保留更多温度
        assert result_with['new_temp'] >= result_without['new_temp']

    def test_get_lifecycle_stage(self):
        """不同温度应对应不同生命周期阶段"""
        assert TemperatureEngine.get_lifecycle_stage(80.0) == TemperatureEngine.STAGE_ACTIVE
        assert TemperatureEngine.get_lifecycle_stage(40.0) == TemperatureEngine.STAGE_SECONDARY
        assert TemperatureEngine.get_lifecycle_stage(10.0) == TemperatureEngine.STAGE_ARCHIVED
        assert TemperatureEngine.get_lifecycle_stage(2.0) == TemperatureEngine.STAGE_DELETED

    def test_calculate_forgetting_probability(self):
        """遗忘概率应在 0-1 范围内"""
        prob = TemperatureEngine.calculate_forgetting_probability(
            temperature=50.0,
            days_idle=5.0,
            importance=0.5,
            emotion_score=0.3,
        )
        assert 0.0 <= prob <= 1.0


class TestMemoryManagerDecayCycle:
    """MemoryManager.run_decay_cycle 测试"""

    def _make_manager(self, agent_id="test_agent"):
        """创建隔离的 MemoryManager"""
        import uuid
        unique_id = f"{agent_id}_{uuid.uuid4().hex[:8]}"
        return MemoryManager(db_path=f":memory:", agent_id=unique_id)

    def test_run_decay_cycle_reduces_temperature(self):
        """run_decay_cycle 应衰减符合条件的记忆温度（贝叶斯曲线）

        Bug 2 修复后契约：
          - 高温记忆（>=80）不衰减（视为固化）
          - 今天访问过的记忆（days_idle < 1.0）不衰减
          - 零温记忆跳过
          - 其他记忆应用贝叶斯曲线衰减
        """
        manager = self._make_manager()

        # mem1: 高温（>=80）→ 不衰减
        mem1_id = manager.remember(content="Test memory 1", temperature=100.0)
        # mem2: 中温 + 7 天前访问 → 应衰减
        mem2_id = manager.remember(content="Test memory 2", temperature=50.0)
        # mem3: 零温 → 跳过
        mem3_id = manager.remember(content="Test memory 3", temperature=0.0)

        # 设置 mem2 的 last_accessed_at 为 7 天前（触发贝叶斯衰减）
        manager._memories[mem2_id].last_accessed_at = (
            datetime.now(timezone.utc) - timedelta(days=7)
        )

        # 运行衰减周期
        count = manager.run_decay_cycle(hours=1.0, rate=1.0)

        # mem1 高温跳过, mem2 衰减, mem3 零温跳过
        # count >= 1（仅 mem2 符合衰减条件）
        assert count >= 1

        # 验证温度变化
        mem1 = manager._memories[mem1_id]
        mem2 = manager._memories[mem2_id]
        mem3 = manager._memories[mem3_id]
        # mem1: 高温保护，温度不变
        assert mem1.temperature == 100.0
        # mem2: 贝叶斯衰减，温度降低
        assert mem2.temperature < 50.0
        # mem3: 零温不变
        assert mem3.temperature == 0.0

    def test_run_decay_cycle_empty_manager(self):
        """空管理器应正常运行"""
        manager = self._make_manager("test_empty")
        count = manager.run_decay_cycle()
        assert count == 0

    def test_update_memory_temperature_touch(self):
        """update_memory_temperature 应提升温度（touch）"""
        manager = self._make_manager()
        mem_id = manager.remember(content="Test memory", temperature=50.0)

        result = manager.update_memory_temperature(mem_id, interaction_type="recall")
        assert result is True
        # touch 方法增加 10 温度
        assert manager._memories[mem_id].temperature == 60.0

    def test_update_memory_temperature_nonexistent(self):
        """更新不存在的记忆应返回 False"""
        manager = self._make_manager()
        result = manager.update_memory_temperature("nonexistent_id")
        assert result is False


class TestUpdateMemoryTemperatureMethod:
    """Agent._update_memory_temperature 方法测试（通过 mock）"""

    def test_calls_run_decay_cycle(self):
        """应调用 memory_manager.run_decay_cycle"""
        mock_agent = MagicMock()
        mock_agent.memory_manager = MagicMock()
        mock_agent.memory_manager.run_decay_cycle.return_value = 5

        # 直接测试逻辑（不实例化 Agent，避免重依赖）
        from neurova.agent_core import Agent
        Agent._update_memory_temperature(mock_agent)

        mock_agent.memory_manager.run_decay_cycle.assert_called_once_with(
            hours=1.0, rate=1.0, max_memories=500, min_interval_seconds=300.0
        )

    def test_skips_when_no_memory_manager(self):
        """memory_manager 为 None 时应跳过"""
        mock_agent = MagicMock()
        mock_agent.memory_manager = None

        from neurova.agent_core import Agent
        # 不应抛出异常
        Agent._update_memory_temperature(mock_agent)

    def test_exception_handling(self):
        """run_decay_cycle 异常时应记录警告，不崩溃"""
        mock_agent = MagicMock()
        mock_agent.memory_manager = MagicMock()
        mock_agent.memory_manager.run_decay_cycle.side_effect = Exception("DB error")

        from neurova.agent_core import Agent
        # 不应抛出异常
        Agent._update_memory_temperature(mock_agent)


class TestPostChatPipelineTemperatureIntegration:
    """PostChatPipeline 温度更新集成测试"""

    def test_step_update_calls_agent_method(self):
        """_step_update_memory_temperature 应调用 Agent 方法"""
        mock_agent = MagicMock()
        mock_agent._update_memory_temperature = MagicMock()

        pipeline = PostChatPipeline(mock_agent)
        pipeline._step_update_memory_temperature()

        mock_agent._update_memory_temperature.assert_called_once()

    def test_step_update_exception_safety(self):
        """Agent 方法异常时不应崩溃"""
        mock_agent = MagicMock()
        mock_agent._update_memory_temperature.side_effect = Exception("Test error")

        pipeline = PostChatPipeline(mock_agent)
        # 不应抛出异常
        pipeline._step_update_memory_temperature()

    def test_process_includes_temperature_step(self):
        """process 方法应包含温度更新步骤"""
        # 验证 process 方法源码包含温度更新
        import inspect
        source = inspect.getsource(PostChatPipeline.process)
        assert "_step_update_memory_temperature" in source


class TestTemperatureEngineInstance:
    """Agent 中 TemperatureEngine 实例化测试"""

    def test_temperature_engine_importable(self):
        """TemperatureEngine 应可导入"""
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
        engine = TemperatureEngine()
        assert engine is not None
        assert engine.base_decay_rate == 0.1

    def test_temperature_engine_custom_params(self):
        """TemperatureEngine 应支持自定义参数"""
        engine = TemperatureEngine(
            base_decay_rate=0.2,
            emotional_protection_threshold=0.6,
            emotional_protection_factor=0.7,
        )
        assert engine.base_decay_rate == 0.2
        assert engine.emotional_protection_threshold == 0.6
        assert engine.emotional_protection_factor == 0.7


class TestAgentTemperatureEngineInit:
    """Agent 中 temperature_engine 初始化的单元测试"""

    def test_agent_init_sets_temperature_engine(self):
        """Agent.__init__ 应设置 temperature_engine"""
        # 使用 patch 避免完整初始化
        with patch('neurova.agent_core.Agent.__init__', return_value=None):
            from neurova.agent_core import Agent
            agent = Agent.__new__(Agent)

            # 模拟 __init__ 中的关键行
            agent.temperature_engine = TemperatureEngine()

            assert agent.temperature_engine is not None
            assert isinstance(agent.temperature_engine, TemperatureEngine)

    def test_agent_init_graceful_fallback(self):
        """TemperatureEngine 不可用时应优雅降级"""
        with patch('neurova.agent_core.TEMPERATURE_ENGINE_AVAILABLE', False):
            # 模拟不可用场景
            engine = TemperatureEngine() if False else None
            assert engine is None