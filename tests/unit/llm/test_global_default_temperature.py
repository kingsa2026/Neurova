"""
全局默认生成温度（2026-09-10，系统设置大模型 tab 迁移决策）

用户问题：系统设置「大模型」tab 的温度有没有真用？迁到记忆设置面板，
先确定隔离机制。

**隔离机制终审**：温度的真实生效链是 agent 级——
AgentConfig.llm_temperature → LLMConfig.temperature → LLMClient 请求参数。
此前两层都是断链：
1. 系统设置大模型 tab 的温度滑条 → /v1/settings（内存假存+全链零消费）
2. Agent 表单温度 → agents API 不消费 body.config.temperature（恒默认 0.7）

本批接线后的语义（两层）：
- **全局默认**：记忆设置 `llm.temperature`（data/memory_settings.json 真持久化，
  schema 驱动面板自动渲染）——AgentConfig.llm_temperature=None 时取全局默认。
- **agent 级覆盖**：Agent 表单显式温度经 agents API 落 AgentConfig.llm_temperature，
  覆盖全局默认。
"""
import pytest
from unittest.mock import MagicMock, patch

from neurova.agent_core import AgentConfig
from neurova.cognitive_layers.memory_layer.settings_config import (
    MemorySettingsConfig,
    get_memory_settings,
)


def _find_llm_schema():
    cfg = get_memory_settings()
    return [s for s in cfg.get_schema() if s.get("key") == "llm.temperature"]


class TestGlobalDefaultTemperature:
    def test_schema_registered(self):
        """记忆设置 schema 注册 llm.temperature（面板自动渲染）。"""
        schema = _find_llm_schema()
        assert schema, "llm.temperature 必须注册进记忆设置 schema"
        entry = schema[0]
        assert entry["type"] == "float"
        assert entry["default"] == pytest.approx(0.7)
        assert entry["min"] == 0.0 and entry["max"] == 2.0

    def test_agent_without_explicit_temperature_uses_global(self):
        """未显式指定温度：AgentConfig 取记忆设置全局默认。"""
        cfg = get_memory_settings()
        old = cfg.get("llm.temperature")
        try:
            cfg.update({"llm.temperature": 1.3})
            config = AgentConfig(
                name="t", agent_id="t_temp_g", workspace_path="./agent_workspaces/test"
            )
            assert config.llm_config.temperature == pytest.approx(1.3)
        finally:
            cfg.update({"llm.temperature": old})
            cfg.save()

    def test_explicit_agent_temperature_overrides_global(self):
        """显式指定温度：agent 级覆盖全局默认。"""
        cfg = get_memory_settings()
        old = cfg.get("llm.temperature")
        try:
            cfg.update({"llm.temperature": 0.9})
            config = AgentConfig(
                name="t",
                agent_id="t_temp_o",
                workspace_path="./agent_workspaces/test",
                llm_temperature=0.2,
            )
            assert config.llm_config.temperature == pytest.approx(0.2)
        finally:
            cfg.update({"llm.temperature": old})
            cfg.save()

    def test_global_config_read_failure_falls_back_07(self):
        """记忆设置读取异常：回落 0.7，不崩构造。"""
        with patch(
            "neurova.cognitive_layers.memory_layer.settings_config.get_memory_settings",
            side_effect=RuntimeError("boom"),
        ):
            config = AgentConfig(
                name="t",
                agent_id="t_temp_f",
                workspace_path="./agent_workspaces/test",
                llm_temperature=None,
            )
        assert config.llm_config.temperature == pytest.approx(0.7)
