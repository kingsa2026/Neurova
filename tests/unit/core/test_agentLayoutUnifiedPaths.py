# -*- coding: utf-8 -*-
"""agent 数据落点统一判据（v2）。

目标布局（全部相对同一个 agent 根）：

    data/<agent_id>/
        agent_config.json
        soul.json
        personality.json
        sleep_settings.json
        media_config.json
        seen_cursors.json
        context_ledger.db
        checkpoints.git/
        sessions/
        workspaces/
        memory/
        skills/
        proposals/
        evolution/
        trajectories/<user>/

这组判据只认**新布局**：生产默认必须落在 `data/<agent_id>/` 下，不允许再出现
`agent_workspaces/<id>`、`data/sessions/<id>`、`data/agents/<id>/skills` 等分散根。
`NEUROVA_AGENT_WORKSPACES_DIR` 仍可注入，但注入的是 agent 根目录的父目录，
注入后的形状必须与生产同构（`<注入根>/<id>/workspaces`）。
"""
from pathlib import Path

import pytest

import neurova.core.agent_workspaces as aw


@pytest.fixture()
def unified(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv(aw.AGENT_WORKSPACES_ENV, raising=False)
    return tmp_path


def test_agent_root_is_data_agent_id(unified):
    assert aw.get_agent_root_dir("kai") == unified / "data" / "kai"
    assert aw.get_agent_root_dir("") == unified / "data" / "default"


def test_four_primary_faces_under_agent_root(unified):
    root = unified / "data" / "kai"
    assert aw.get_agent_workspace_dir("kai") == root / "workspaces"
    assert aw.get_agent_memory_dir("kai") == root / "memory"
    assert aw.get_agent_sessions_dir("kai") == root / "sessions"
    assert aw.get_agent_config_path("kai") == root / "agent_config.json"


def test_remaining_agent_faces_under_agent_root(unified):
    root = unified / "data" / "kai"
    assert aw.get_agent_soul_path("kai") == root / "soul.json"
    assert aw.get_agent_personality_path("kai") == root / "personality.json"
    assert aw.get_agent_sleep_settings_path("kai") == root / "sleep_settings.json"
    assert aw.get_agent_media_config_path("kai") == root / "media_config.json"
    assert aw.get_agent_cursors_path("kai") == root / "seen_cursors.json"
    assert aw.get_agent_context_ledger_path("kai") == root / "context_ledger.db"
    assert aw.get_agent_checkpoints_dir("kai") == root / "checkpoints.git"
    assert aw.get_agent_skills_dir("kai") == root / "skills"
    assert aw.get_agent_proposals_dir("kai") == root / "proposals"
    assert aw.get_agent_evolution_dir("kai") == root / "evolution"
    assert aw.get_agent_trajectories_dir("kai") == root / "trajectories"
    assert aw.get_agent_trajectory_dir("kai", "alice") == root / "trajectories" / "alice"


def test_memory_helpers_resolve_under_agent_memory_root(unified):
    root = unified / "data" / "kai"
    assert aw.agentMemoryDirUnder(aw.get_agent_root_dir("kai")) == root / "memory"
    assert aw.agentMemoryDbPathUnder(aw.get_agent_root_dir("kai")) == root / "memory" / "memory.db"


def test_injected_root_keeps_same_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv(aw.AGENT_WORKSPACES_ENV, str(tmp_path / "agents"))
    assert aw.get_agent_root_dir("kai") == tmp_path / "agents" / "kai"
    assert aw.get_agent_workspace_dir("kai") == tmp_path / "agents" / "kai" / "workspaces"
    assert aw.get_agent_memory_dir("kai") == tmp_path / "agents" / "kai" / "memory"
    assert aw.get_agent_sessions_dir("kai") == tmp_path / "agents" / "kai" / "sessions"


def test_reserved_and_unsafe_ids_are_rejected(unified):
    for bad in ("agents", "sessions", "personality", "knowledge", "../evil", "a/b", "a b", "."):
        with pytest.raises(ValueError):
            aw.get_agent_root_dir(bad)
    assert aw.is_reserved_agent_id("knowledge") is True
    assert aw.is_reserved_agent_id("kai") is False


def test_discover_agent_ids_only_returns_agent_roots(unified):
    data = unified / "data"
    (data / "kai").mkdir(parents=True)
    (data / "kai" / "agent_config.json").write_text("{}", encoding="utf-8")
    (data / "default" / "workspaces").mkdir(parents=True)
    (data / "knowledge").mkdir(parents=True)
    (data / "knowledge" / "knowledge_facts.db").write_text("", encoding="utf-8")
    (data / "sessions").mkdir(parents=True)
    assert aw.discover_agent_ids() == ["default", "kai"]
