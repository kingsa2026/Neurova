"""技能召回与进化开关：收口 app_settings 高级段 + 默认全开（2026-09-15）

契约：
- 三开关落 data/app_settings.json advanced 段（desktop_provider 同族，后端热读）：
  skill_catalog_enabled / skill_schema_budget_enabled / evolution_queue_enabled，
  **默认全部 True**（用户拍板 2026-09-15）；
- 三态优先级：agent 显式配置（AgentConfig 非 None）> 全局设置 > 内置默认；
  AgentConfig 默认改 None（=跟随全局，存量显式 True/False 语义不变）；
- NEUROVA_EVOLUTION_QUEUE 环境变量保留且显式值最优先（运维/测试逃生门），
  未显式设置时跟随全局设置（默认开）。
"""

import json

import pytest

from neurova.core import app_settings as appset
from neurova.evolution.job_queue import queue_enabled

NEW_KEYS = {
    "skill_catalog_enabled": True,
    "skill_schema_budget_enabled": True,
    "evolution_queue_enabled": True,
    "skill_schema_max": 20,
}


def test_advanced_defaults_contain_switches_on():
    for key, default in NEW_KEYS.items():
        assert key in appset.ADVANCED_DEFAULTS, key
        assert appset.ADVANCED_DEFAULTS[key] == default


def test_settings_roundtrip_persists_overrides(tmp_path):
    path = tmp_path / "app_settings.json"
    appset.save_app_settings(
        "advanced",
        {"skill_catalog_enabled": False, "skill_schema_budget_enabled": False},
        path=path,
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["advanced"]["skill_catalog_enabled"] is False
    merged = appset.load_app_settings(path)
    assert merged["advanced"]["skill_catalog_enabled"] is False
    # 未覆盖的键保持默认开
    assert merged["advanced"]["evolution_queue_enabled"] is True


# ── queue_enabled 三级优先级 ───────────────────────────────


def test_queue_enabled_default_on(monkeypatch, tmp_path):
    monkeypatch.delenv("NEUROVA_EVOLUTION_QUEUE", raising=False)
    monkeypatch.setattr(appset, "_settings_path", lambda path=None: tmp_path / "s.json")
    assert queue_enabled() is True


def test_queue_enabled_env_false_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("NEUROVA_EVOLUTION_QUEUE", "0")
    monkeypatch.setattr(appset, "_settings_path", lambda path=None: tmp_path / "s.json")
    assert queue_enabled() is False


def test_queue_enabled_settings_false_without_env(monkeypatch, tmp_path):
    monkeypatch.delenv("NEUROVA_EVOLUTION_QUEUE", raising=False)
    path = tmp_path / "s.json"
    appset.save_app_settings("advanced", {"evolution_queue_enabled": False}, path=path)
    monkeypatch.setattr(appset, "_settings_path", lambda p=None: path)
    assert queue_enabled() is False


def test_queue_enabled_env_true_overrides_settings_false(monkeypatch, tmp_path):
    """运维逃生门：env 显式值压过全局设置。"""
    monkeypatch.setenv("NEUROVA_EVOLUTION_QUEUE", "1")
    path = tmp_path / "s.json"
    appset.save_app_settings("advanced", {"evolution_queue_enabled": False}, path=path)
    monkeypatch.setattr(appset, "_settings_path", lambda p=None: path)
    assert queue_enabled() is True


def test_queue_enabled_settings_read_failure_falls_back_on(monkeypatch):
    """设置存储故障不得瘫痪进化——回退默认开（fail-open 到有损侧：inline 路径同样可用）。"""

    def _boom(*a, **k):
        raise RuntimeError("storage down")

    monkeypatch.delenv("NEUROVA_EVOLUTION_QUEUE", raising=False)
    monkeypatch.setattr(appset, "get_advanced_settings", _boom)
    assert queue_enabled() is True


# ── AgentConfig 三态（None=跟随全局）────────────────────────


def test_agent_config_flags_default_none():
    from neurova.agent_core import AgentConfig  # Agent 配置类名以实际为准

    import inspect

    sig = inspect.signature(AgentConfig.__init__)
    for flag in ("skill_catalog_enabled", "skill_schema_budget_enabled"):
        assert flag in sig.parameters
        assert sig.parameters[flag].default is None, "默认应为 None=跟随全局开关"


# ── orchestrator 消费面：三态解析 ──────────────────────────


class _Cfg:
    def __init__(self, catalog=None):
        self.skill_catalog_enabled = catalog
        self.skill_catalog_budget_chars = 8000


def _section(config_flag, global_flag, monkeypatch, tmp_path):
    import types

    from neurova.context.orchestrator import ContextOrchestrator

    path = tmp_path / "s.json"
    appset.save_app_settings("advanced", {"skill_catalog_enabled": global_flag}, path=path)
    monkeypatch.setattr(appset, "_settings_path", lambda p=None: path)

    class _Reg:
        skills = {"a": types.SimpleNamespace(name="a", description="d", config={}, enabled=True)}

    stub = types.SimpleNamespace(config=_Cfg(config_flag), skill_registry=_Reg())
    stub._resolve_recall_flag = types.MethodType(ContextOrchestrator._resolve_recall_flag, stub)
    return types.MethodType(ContextOrchestrator._skill_catalog_section, stub)()


def test_config_explicit_false_wins_over_global_on(monkeypatch, tmp_path):
    assert _section(False, True, monkeypatch, tmp_path) == ""


def test_config_explicit_true_wins_over_global_off(monkeypatch, tmp_path):
    assert "可用技能目录" in _section(True, False, monkeypatch, tmp_path)


def test_config_none_follows_global_on(monkeypatch, tmp_path):
    assert "可用技能目录" in _section(None, True, monkeypatch, tmp_path)


def test_config_none_follows_global_off(monkeypatch, tmp_path):
    assert _section(None, False, monkeypatch, tmp_path) == ""
