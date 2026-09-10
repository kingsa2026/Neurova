"""
agent 表单温度断链修复（2026-09-10）

AgentFormPage 发 config.temperature → 后端此前不消费（恒默认 0.7）。
接线后：create/update 消费、_save_agent_config 落盘、_config_from_saved 回读。
"""
import pytest

from neurova.api.endpoints.agent import (
    _temperature_from_body_config,
    _save_agent_config,
)


class TestTemperatureFromBodyConfig:
    def test_extracts_and_clamps(self):
        assert _temperature_from_body_config({"temperature": 1.4}) == 1.4
        assert _temperature_from_body_config({"temperature": 5.0}) == 2.0
        assert _temperature_from_body_config({"temperature": -1}) == 0.0

    def test_absent_and_invalid_return_none(self):
        """未提及键 / 非法值 → None（update 局部语义，不覆盖）。"""
        assert _temperature_from_body_config({}) is None
        assert _temperature_from_body_config({"temperature": "abc"}) is None
        assert _temperature_from_body_config(None) is None


class TestAgentConfigPersistence:
    def test_save_persists_temperature(self, tmp_path):
        from types import SimpleNamespace

        agent = SimpleNamespace(
            config=SimpleNamespace(
                name="t",
                description="",
                llm_provider="",
                llm_config=SimpleNamespace(model="m1", temperature=1.1),
                workspace_path=str(tmp_path),
                owner_user_id="u1",
                enable_tts=False,
                tts_engine="auto",
                tts_voice="",
                tts_speed=1.0,
                tts_pitch=1.0,
            )
        )
        _save_agent_config(agent)
        import json
        data = json.load(open(tmp_path / "agent_config.json", encoding="utf-8"))
        assert data["temperature"] == pytest.approx(1.1)

    def test_save_without_temperature_omits_key(self, tmp_path):
        """temperature=None（全局默认语义）不落键 → 重建走全局默认。"""
        from types import SimpleNamespace

        agent = SimpleNamespace(
            config=SimpleNamespace(
                name="t",
                description="",
                llm_provider="",
                llm_config=SimpleNamespace(model="m1", temperature=None),
                workspace_path=str(tmp_path),
                owner_user_id="u1",
                enable_tts=False,
                tts_engine="auto",
                tts_voice="",
                tts_speed=1.0,
                tts_pitch=1.0,
            )
        )
        _save_agent_config(agent)
        import json
        data = json.load(open(tmp_path / "agent_config.json", encoding="utf-8"))
        assert "temperature" not in data

    def test_config_from_saved_reads_back(self, tmp_path):
        """app._config_from_saved 回读落盘温度（覆盖链最后一环）。"""
        from neurova.api.app import _agent_config_from_saved

        import json
        cfg = {"name": "t", "model": "m1", "temperature": 0.35}
        json.dump(cfg, open(tmp_path / "agent_config.json", "w", encoding="utf-8"),
                  ensure_ascii=False)

        agent_config = _agent_config_from_saved(dict(cfg), agent_id="t_back", workspace_path=str(tmp_path))
        assert agent_config.llm_config.temperature == pytest.approx(0.35)

    def test_config_from_saved_absent_uses_global_default(self, tmp_path):
        """未落盘温度 → AgentConfig.llm_temperature=None → 记忆设置全局默认。"""
        from neurova.api.app import _agent_config_from_saved

        cfg = {"name": "t", "model": "m1"}
        agent_config = _agent_config_from_saved(dict(cfg), agent_id="t_back2", workspace_path=str(tmp_path))
        assert agent_config.llm_config.temperature == pytest.approx(0.7)
