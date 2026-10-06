"""§6-3 RSI 运行参数入配置 — 红灯先行的契约测试(2026-10-06)。

此前三处硬编码与 evolution_settings 的"管理员可调"哲学不一致:
- 递归棘轮每轮候选数 [50,10,3](rsi/orchestrator.py,原 rounds=3 硬编码);
- backoff(收敛/度量失明)降频巡检窗口 20 轮(post_chat_pipeline.py);
- 经验/事件触发 RSI 迭代的节流窗口 60 秒(closed_loop.py)。

本文件钉住:字段存在且默认值与原硬编码逐字一致(零行为漂移)、
round-trip 持久化、旧配置文件(无新键)照常加载、坏值收敛回默认、
三个消费点读的是文件值而非各自字面量。
"""

import json

import pytest

from neurova.evolution.evolution_settings import (
    EvolutionSettings,
    load_settings,
    update_settings,
)


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "evolution_settings.json"
    monkeypatch.setenv("NEUROVA_EVOLUTION_SETTINGS", str(path))
    return path


class TestKnobDefaults:
    def test_defaults_preserve_current_behavior(self):
        """默认值 = 原硬编码值(零行为漂移)。"""
        s = EvolutionSettings()
        assert s.rsi_event_throttle_seconds == 60.0
        assert s.rsi_backoff_every_turns == 20
        assert s.rsi_ratchet_candidates == [50, 10, 3]


class TestRoundTrip:
    def test_update_persists_and_loads(self, settings_file):
        update_settings(
            rsi_event_throttle_seconds=90.0,
            rsi_backoff_every_turns=40,
            rsi_ratchet_candidates=[4, 2, 1],
        )
        loaded = load_settings()
        assert loaded.rsi_backoff_every_turns == 40
        assert loaded.rsi_event_throttle_seconds == 90.0
        assert loaded.rsi_ratchet_candidates == [4, 2, 1]

    def test_old_config_file_without_new_keys_still_loads(self, settings_file):
        """存量 5 键配置文件(升级前落盘)照常加载,新字段回默认。"""
        settings_file.write_text(json.dumps({
            "text_evolution": True,
            "lifecycle_sweep": True,
            "lifecycle_interval_hours": 24,
            "judge_model": "",
            "optimizer_model": "",
        }), encoding="utf-8")
        s = load_settings()
        assert s.text_evolution is True
        assert s.rsi_ratchet_candidates == [50, 10, 3]
        assert s.rsi_backoff_every_turns == 20
        assert s.rsi_event_throttle_seconds == 60.0


class TestCoercion:
    def test_bad_values_fall_back_to_defaults(self, settings_file):
        """脏配置(类型错/负值)收敛回默认,不让坏文件阻断进化装配。"""
        settings_file.write_text(json.dumps({
            "rsi_event_throttle_seconds": "fast",
            "rsi_backoff_every_turns": -3,
            "rsi_ratchet_candidates": "aggressive",
        }), encoding="utf-8")
        s = load_settings()
        assert s.rsi_event_throttle_seconds == 60.0
        assert s.rsi_backoff_every_turns == 20
        assert s.rsi_ratchet_candidates == [50, 10, 3]

    def test_candidates_clamped_positive(self, settings_file):
        """候选数逐项收敛为正整数(0/负值抬到 1)。"""
        update_settings(rsi_ratchet_candidates=[0, 7, 2])
        assert load_settings().rsi_ratchet_candidates == [1, 7, 2]

    def test_bad_element_in_list_falls_back_whole(self, settings_file):
        """列表内含不可收敛元素 → 整组回默认(不做静默截半)。"""
        update_settings(rsi_ratchet_candidates=[4, "x", 1])
        assert load_settings().rsi_ratchet_candidates == [50, 10, 3]


class TestConsumers:
    """三个消费点读文件值——钉死"配置真被消费",不是只写不读的断点。"""

    def test_orchestrator_ratchet_reads_settings(self, settings_file):
        settings_file.write_text(
            json.dumps({"rsi_ratchet_candidates": [4, 2, 1]}), encoding="utf-8")
        from neurova.evolution.rsi.orchestrator import _ratchet_candidates_from_settings

        assert _ratchet_candidates_from_settings() == [4, 2, 1]

    def test_pipeline_backoff_reads_settings(self, settings_file):
        settings_file.write_text(
            json.dumps({"rsi_backoff_every_turns": 7}), encoding="utf-8")
        from neurova.post_chat_pipeline import _rsi_backoff_every_turns

        assert _rsi_backoff_every_turns() == 7

    def test_closed_loop_throttle_reads_settings(self, settings_file):
        settings_file.write_text(
            json.dumps({"rsi_event_throttle_seconds": 15.5}), encoding="utf-8")
        from neurova.evolution.closed_loop import _default_rsi_iteration_interval

        assert _default_rsi_iteration_interval() == 15.5
