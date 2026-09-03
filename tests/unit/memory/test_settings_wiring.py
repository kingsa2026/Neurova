"""记忆配置接线测试 — settings_config 保存的参数必须真实生效

根因（2026-08-29）：配置页保存链路（PUT /memory-settings/settings →
MemorySettingsConfig.update_and_save → data/memory_settings.json）完全正常，
但记忆核心从不读取该配置（孤儿配置）——用户在配置页改参数后"保存成功"，
记忆系统行为却纹丝不动。

本测试锁定 4 个已接线参数的行为契约（settings 默认值与原硬编码一致，
接线零默认行为变化；仅当用户修改配置时行为才会改变）：

- manager.new_memory_temperature  → MemoryManager.remember 默认温度
- manager.new_memory_importance   → MemoryManager.remember 默认重要性
- manager.hot_memories_threshold  → MemoryManager.get_hot_memories 过滤阈值
- temperature.decay_rate          → run_decay_cycle 的贝叶斯衰减基础速率
"""

import uuid
from datetime import datetime, timezone, timedelta

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.settings_config import (
    get_memory_settings,
    MemorySettingsConfig,
)


@pytest.fixture
def settings(tmp_path):
    """隔离的配置单例：指向 tmp 目录，测后重置，防污染真实 data/memory_settings.json"""
    MemorySettingsConfig.reset_instance()
    cfg = get_memory_settings(str(tmp_path))
    yield cfg
    MemorySettingsConfig.reset_instance()


def _make_manager(agent_id="wiring_test"):
    unique_id = f"{agent_id}_{uuid.uuid4().hex[:8]}"
    return MemoryManager(db_path=":memory:", agent_id=unique_id)


class TestRememberUsesSettings:
    def test_new_memory_temperature_and_importance(self, settings):
        """不显式传温度/重要性时，新记忆使用配置值"""
        settings.update(
            {
                "manager.new_memory_temperature": 42.0,
                "manager.new_memory_importance": 7.5,
            }
        )
        mgr = _make_manager()
        mid = mgr.remember("配置化默认值测试")
        mem = mgr._memories[mid]
        assert mem.temperature == 42.0
        assert mem.importance == 7.5

    def test_explicit_args_override_settings(self, settings):
        """调用方显式传参时优先于配置"""
        settings.update({"manager.new_memory_temperature": 42.0})
        mgr = _make_manager()
        mid = mgr.remember("显式参数优先", temperature=10.0, importance=1.0)
        mem = mgr._memories[mid]
        assert mem.temperature == 10.0
        assert mem.importance == 1.0

    def test_default_config_keeps_legacy_behavior(self, settings):
        """未修改配置时保持历史硬编码行为（100/50），保证零默认回归"""
        mgr = _make_manager()
        mid = mgr.remember("默认行为不变")
        mem = mgr._memories[mid]
        assert mem.temperature == 100.0
        assert mem.importance == 50.0


class TestHotMemoriesThreshold:
    def _seed(self, mgr):
        for t in (90.0, 70.0, 50.0):
            mgr.remember(f"m{t}", temperature=t)

    def test_get_hot_memories_uses_settings_threshold(self, settings):
        """阈值来自配置：60 时 90/70 命中，50 被过滤。

        注意 recall 会 touch() 命中记忆（+10 封顶 100）：90→100、70→80。
        若 50 未被过滤，其 touch 后 60.0 会出现在结果里。
        """
        settings.update({"manager.hot_memories_threshold": 60.0})
        mgr = _make_manager()
        self._seed(mgr)
        temps = sorted(
            (m["temperature"] for m in mgr.get_hot_memories()), reverse=True
        )
        assert temps == [100.0, 80.0]

    def test_explicit_threshold_overrides_settings(self, settings):
        """显式传 min_temperature 时优先于配置"""
        settings.update({"manager.hot_memories_threshold": 60.0})
        mgr = _make_manager()
        self._seed(mgr)
        assert mgr.get_hot_memories(min_temperature=100.0) == []

    def test_default_threshold_keeps_legacy_behavior(self, settings):
        """未修改配置时保持 80 阈值：仅 90 命中（touch 后 100）"""
        mgr = _make_manager()
        self._seed(mgr)
        temps = sorted(
            (m["temperature"] for m in mgr.get_hot_memories()), reverse=True
        )
        assert temps == [100.0]


class TestDecayRate:
    def test_run_decay_cycle_uses_settings_decay_rate(self, settings):
        """同样一条 7 天未访问的中温记忆：decay_rate 越大衰减越多。

        温度须 <80：on_decay 对高温记忆(>=80)有硬编码固化保护。
        """
        temps = {}
        for rate in (0.1, 0.5):
            settings.update({"temperature.decay_rate": rate})
            mgr = _make_manager()
            mid = mgr.remember("衰减速率测试", temperature=50.0, importance=1.0)
            mem = mgr._memories[mid]
            mem.last_accessed_at = datetime.now(timezone.utc) - timedelta(days=7)
            mgr.run_decay_cycle()
            temps[rate] = mem.temperature
        # 显著差阈值 0.01：排除两轮 days_idle 毫秒级漂移的曲线噪声
        assert temps[0.1] - temps[0.5] > 0.01, (
            f"decay_rate=0.5 应比 0.1 衰减显著更多: {temps}"
        )


class TestTemperatureDomainClamp:
    """温度域统一为 [0, 100]：系统内 touch/on_access/on_decay 均 clamp 100，
    但 Memory 构造无兜底——批量导入曾把 68.6 万条记忆温度灌到 13363.36，
    导致 hot 列表（任何阈值）永远被污染记忆占满、配置页阈值形同虚设。"""

    def test_over_domain_temperature_downgraded(self):
        """超域温度（污染数据）降级为中温 50，避免霸占 hot 列表"""
        from neurova.cognitive_layers.memory_layer.models import Memory

        m = Memory(id="x", temperature=13363.36)
        assert m.temperature == 50.0

    def test_negative_temperature_clamped(self):
        from neurova.cognitive_layers.memory_layer.models import Memory

        m = Memory(id="x", temperature=-5.0)
        assert m.temperature == 0.0

    def test_normal_temperature_untouched(self):
        from neurova.cognitive_layers.memory_layer.models import Memory

        assert Memory(id="x", temperature=80.0).temperature == 80.0
        assert Memory(id="x", temperature=0.0).temperature == 0.0
        assert Memory(id="x", temperature=100.0).temperature == 100.0


class TestTemperatureRuntimeParams:
    """temperature.access_boost / temperature.max / temperature.min 接线。

    设计对齐：核心事实温度域 [0, 100]（touch/on_access/on_decay 均 clamp 100），
    schema 原默认 0.3/0.01/1.0 是 0~1 域幻觉，与核心量级冲突 → 修正为
    access_boost=10（touch 历史硬编码）、min=0、max=100。
    """

    def test_schema_defaults_match_core_reality(self, settings):
        """schema 默认值必须与核心历史硬编码一致（保证零默认回归）"""
        assert settings.get("temperature.access_boost") == 10.0
        assert settings.get("temperature.min") == 0.0
        assert settings.get("temperature.max") == 100.0

    def test_touch_uses_access_boost(self, settings):
        """touch 的升温量来自 temperature.access_boost"""
        from neurova.cognitive_layers.memory_layer.models import Memory

        settings.update({"temperature.access_boost": 3.0})
        m = Memory(id="x", temperature=50.0)
        m.touch()
        assert m.temperature == 53.0

    def test_touch_caps_at_configured_max(self, settings):
        """touch 的封顶来自 temperature.max（默认 100 与历史一致）"""
        from neurova.cognitive_layers.memory_layer.models import Memory

        settings.update({"temperature.max": 60.0, "temperature.access_boost": 10.0})
        m = Memory(id="x", temperature=55.0)
        m.touch()
        assert m.temperature == 60.0

    def test_on_decay_respects_min_temperature(self, settings):
        """衰减不会被压到 temperature.min 之下（默认 0 与历史一致）"""
        settings.update({"temperature.min": 30.0})
        mgr = _make_manager()
        mid = mgr.remember("min floor 测试", temperature=40.0, importance=1.0)
        mem = mgr._memories[mid]
        mem.last_accessed_at = datetime.now(timezone.utc) - timedelta(days=30)
        mgr.run_decay_cycle()
        assert mem.temperature >= 30.0


class TestSchemaReservedParams:
    """仍未接入主链路的引擎参数必须在 schema 描述中标注【预留】，
    避免用户在配置页修改后误以为已生效。"""

    # 2026-08-29 接入后剩余孤岛：activation 组（EnhancedMemoryRetriever 未接）、
    # auto_context 组（周期任务自动删改数据，不默认启用）、graph.time_decay
    # （引擎内按查询意图分型预设，不单配）、vector_search 的 sklearn 词表参数
    RESERVED_KEYS = {
        "auto_context.update_interval",
        "auto_context.compression_threshold_days",
        "auto_context.temperature_decay_rate",
        "activation.decay_rate",
        "activation.weight_context",
        "activation.weight_semantic",
        "activation.weight_emotional",
        "activation.weight_temporal",
        "activation.weight_frequency",
        "activation.weight_spread",
        "graph.time_decay",
        "vector_search.max_features",
        "vector_search.min_df",
        "vector_search.max_df",
    }

    def test_orphan_groups_marked_reserved(self):
        from neurova.cognitive_layers.memory_layer.settings_config import (
            PARAM_SCHEMAS,
        )

        unmarked = [
            s.key
            for s in PARAM_SCHEMAS
            if s.key in self.RESERVED_KEYS and "预留" not in s.description
        ]
        assert not unmarked, f"孤岛引擎参数未标注预留: {unmarked}"

    def test_active_groups_not_marked_reserved(self):
        from neurova.cognitive_layers.memory_layer.settings_config import (
            PARAM_SCHEMAS,
        )

        wired_keys = {
            "temperature.decay_rate",
            "temperature.access_boost",
            "temperature.min",
            "temperature.max",
            "manager.new_memory_temperature",
            "manager.new_memory_importance",
            "manager.hot_memories_threshold",
            "threshold.default",
            "compression.similarity_threshold",
            "compression.max_memories_per_group",
            "compression.time_window_hours",
            "compression.importance_threshold",
            "compression.enable_llm_compression",
            "graph.min_strength",
            "graph.beam_width",
            "vector_search.cache_max_size",
            "vector_search.moe_index_limit",
        }
        wrongly_marked = [
            s.key
            for s in PARAM_SCHEMAS
            if s.key in wired_keys and "预留" in s.description
        ]
        assert not wrongly_marked, f"已接线参数被误标预留: {wrongly_marked}"
