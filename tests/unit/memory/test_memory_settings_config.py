"""
测试 MemorySettingsConfig 配置中心

验证：
1. 默认值正确读取
2. 参数更新和持久化
3. Schema 校验（类型、范围）
4. 分组读取
5. 重置功能
6. API 端点 CRUD
"""

import json
import os
import tempfile
import pytest
from pathlib import Path


# ============================================================
# 辅助
# ============================================================

def _make_tmp_dir():
    d = tempfile.mkdtemp()
    return d


# ============================================================
# MemorySettingsConfig 单元测试
# ============================================================

class TestMemorySettingsConfig:
    """测试配置中心核心功能"""

    def setup_method(self):
        from neurova.cognitive_layers.memory_layer.settings_config import reset_memory_settings
        reset_memory_settings()

    def teardown_method(self):
        from neurova.cognitive_layers.memory_layer.settings_config import reset_memory_settings
        reset_memory_settings()

    def test_default_values(self):
        """所有参数返回 schema 默认值"""
        from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
        tmp = _make_tmp_dir()
        cfg = get_memory_settings(tmp)

        assert cfg.get("temperature.decay_rate") == 0.1
        # 2026-08-29 温度域对齐核心实现（[0,100]）：access_boost=touch 历史硬编码 +10，
        # min/max 从 0~1 域幻觉修正为 0~100
        assert cfg.get("temperature.access_boost") == 10.0
        assert cfg.get("temperature.min") == 0.0
        assert cfg.get("temperature.max") == 100.0
        assert cfg.get("compression.similarity_threshold") == 0.7
        assert cfg.get("activation.decay_rate") == 0.1
        assert cfg.get("threshold.default") == 0.3
        assert cfg.get("graph.beam_width") == 3
        assert cfg.get("vector_search.max_features") == 10000
        assert cfg.get("manager.new_memory_temperature") == 100.0
        assert cfg.get("auto_context.update_interval") == 3600

    def test_unknown_key_returns_default(self):
        """未知 key 返回指定默认值"""
        from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
        tmp = _make_tmp_dir()
        cfg = get_memory_settings(tmp)
        assert cfg.get("nonexistent.key", "fallback") == "fallback"

    def test_update_single_param(self):
        """更新单个参数"""
        from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
        tmp = _make_tmp_dir()
        cfg = get_memory_settings(tmp)

        updated = cfg.update({"temperature.decay_rate": 0.5})
        assert updated == ["temperature.decay_rate"]
        assert cfg.get("temperature.decay_rate") == 0.5

    def test_update_multiple_params(self):
        """批量更新多个参数"""
        from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
        tmp = _make_tmp_dir()
        cfg = get_memory_settings(tmp)

        updated = cfg.update({
            "temperature.decay_rate": 0.5,
            "compression.similarity_threshold": 0.9,
            "graph.beam_width": 5,
        })
        assert len(updated) == 3
        assert cfg.get("temperature.decay_rate") == 0.5
        assert cfg.get("compression.similarity_threshold") == 0.9
        assert cfg.get("graph.beam_width") == 5

    def test_update_rejects_unknown_key(self):
        """拒绝未知 key"""
        from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
        tmp = _make_tmp_dir()
        cfg = get_memory_settings(tmp)

        updated = cfg.update({"unknown.param": 123})
        assert updated == []

    def test_update_rejects_type_mismatch(self):
        """拒绝类型不匹配"""
        from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
        tmp = _make_tmp_dir()
        cfg = get_memory_settings(tmp)

        # float 字段传 string
        updated = cfg.update({"temperature.decay_rate": "not_a_number"})
        assert updated == []
        # int 字段传 float
        updated = cfg.update({"graph.beam_width": 3.5})
        assert updated == []
        # bool 字段传 int
        updated = cfg.update({"compression.enable_llm_compression": 1})
        assert updated == []

    def test_update_rejects_out_of_range(self):
        """拒绝超出范围的值"""
        from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
        tmp = _make_tmp_dir()
        cfg = get_memory_settings(tmp)

        # decay_rate max=1.0
        updated = cfg.update({"temperature.decay_rate": 1.5})
        assert updated == []
        # beam_width min=1
        updated = cfg.update({"graph.beam_width": 0})
        assert updated == []

    def test_get_section(self):
        """按分组读取"""
        from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
        tmp = _make_tmp_dir()
        cfg = get_memory_settings(tmp)

        section = cfg.get_section("temperature")
        assert "temperature.decay_rate" in section
        assert "temperature.access_boost" in section
        assert "temperature.min" in section
        assert "temperature.max" in section
        assert len(section) == 4

    def test_get_all(self):
        """获取所有参数"""
        from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
        tmp = _make_tmp_dir()
        cfg = get_memory_settings(tmp)

        all_params = cfg.get_all()
        # 应该有 30+ 个参数
        assert len(all_params) >= 30
        assert "temperature.decay_rate" in all_params

    def test_persistence(self):
        """配置持久化到 JSON"""
        from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
        tmp = _make_tmp_dir()
        cfg = get_memory_settings(tmp)

        cfg.update({"temperature.decay_rate": 0.5})
        cfg.save()

        # 重新加载
        from neurova.cognitive_layers.memory_layer.settings_config import reset_memory_settings
        reset_memory_settings()
        cfg2 = get_memory_settings(tmp)
        assert cfg2.get("temperature.decay_rate") == 0.5

    def test_reset_all(self):
        """重置全部参数"""
        from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
        tmp = _make_tmp_dir()
        cfg = get_memory_settings(tmp)

        cfg.update({"temperature.decay_rate": 0.5, "graph.beam_width": 99})
        cfg.reset()
        assert cfg.get("temperature.decay_rate") == 0.1
        assert cfg.get("graph.beam_width") == 3

    def test_reset_specific_keys(self):
        """重置指定 key"""
        from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
        tmp = _make_tmp_dir()
        cfg = get_memory_settings(tmp)

        cfg.update({"temperature.decay_rate": 0.5, "graph.beam_width": 10})
        cfg.reset(["temperature.decay_rate"])
        assert cfg.get("temperature.decay_rate") == 0.1
        assert cfg.get("graph.beam_width") == 10

    def test_update_and_save(self):
        """update_and_save 一步到位"""
        from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
        tmp = _make_tmp_dir()
        cfg = get_memory_settings(tmp)

        updated = cfg.update_and_save({"compression.similarity_threshold": 0.95})
        assert updated == ["compression.similarity_threshold"]

        from neurova.cognitive_layers.memory_layer.settings_config import reset_memory_settings
        reset_memory_settings()
        cfg2 = get_memory_settings(tmp)
        assert cfg2.get("compression.similarity_threshold") == 0.95

    def test_get_schema(self):
        """schema 包含所有元信息"""
        from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
        tmp = _make_tmp_dir()
        cfg = get_memory_settings(tmp)

        schema = cfg.get_schema()
        assert len(schema) >= 30
        # 检查第一个条目
        first = schema[0]
        assert "key" in first
        assert "default" in first
        assert "type" in first
        assert "description" in first
        assert "current" in first

    def test_get_schema_desc_key_contract(self):
        """多语言契约: 每个 schema 条目携带 desc_key（语言包键），前端渲染走 i18n

        根因（2026-09-02 审计）: PARAM_SCHEMAS.description 为中文硬编码,
        MemorySettingsPage 直接透出, 非中文语言界面每条参数说明都是中文。
        契约:
          1. desc_key = "memorySettings.param" + camelCase(key)
          2. 保留 description 作为兼容回退（未接入 i18n 的消费方仍可用）
          3. 33 个参数全部有 desc_key
        """
        from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
        tmp = _make_tmp_dir()
        cfg = get_memory_settings(tmp)

        schema = cfg.get_schema()
        assert len(schema) >= 30
        for entry in schema:
            assert "desc_key" in entry, f"{entry['key']} 缺少 desc_key"
            assert entry["desc_key"], f"{entry['key']} desc_key 为空"
            # 键名规则: memorySettings.param + camelCase(key)（语言包约定为两层 camelCase）
            parts = [p for seg in entry["key"].split(".") for p in seg.split("_") if p]
            expected = "memorySettings.param" + parts[0].lower() + "".join(p.capitalize() for p in parts[1:])
            assert entry["desc_key"] == expected, f"{entry['key']} desc_key 规则不符: {entry['desc_key']}"
            assert "description" in entry and entry["description"], f"{entry['key']} 需保留 description 回退"

    def test_singleton(self):
        """单例模式"""
        from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
        tmp = _make_tmp_dir()
        cfg1 = get_memory_settings(tmp)
        cfg2 = get_memory_settings(tmp)
        assert cfg1 is cfg2

    def test_bool_type(self):
        """布尔类型参数"""
        from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
        tmp = _make_tmp_dir()
        cfg = get_memory_settings(tmp)

        assert cfg.get("compression.enable_llm_compression") is True
        updated = cfg.update({"compression.enable_llm_compression": False})
        assert updated == ["compression.enable_llm_compression"]
        assert cfg.get("compression.enable_llm_compression") is False

    def test_boundary_values(self):
        """边界值测试"""
        from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
        tmp = _make_tmp_dir()
        cfg = get_memory_settings(tmp)

        # 正好在边界上
        updated = cfg.update({"temperature.decay_rate": 1.0})  # max
        assert updated == ["temperature.decay_rate"]

        updated = cfg.update({"temperature.decay_rate": 0.0})  # min
        assert updated == ["temperature.decay_rate"]

        # 超出边界
        updated = cfg.update({"temperature.decay_rate": 1.01})
        assert updated == []
        updated = cfg.update({"temperature.decay_rate": -0.01})
        assert updated == []
