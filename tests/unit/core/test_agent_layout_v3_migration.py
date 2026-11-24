# -*- coding: utf-8 -*-
"""v2→v3 布局迁移器判据：只搬不删、按属主分桶、loaded 跳过、哨兵、幂等、干跑。

用户拍板（2026-11-24）：启动不再自动扫描；管理员可手动全量扫描（哨兵标记），
也可按属主定向扫描；shared agent 落 share 桶。
"""
from __future__ import annotations

import json

import pytest

from neurova.core.agent_layout_migration import (
    ensure_agent_layout_v3,
    migrate_agent_layout_v3,
    v3_migration_done,
)


@pytest.fixture()
def layout(tmp_path, monkeypatch):
    monkeypatch.delenv("NEUROVA_AGENT_WORKSPACES_DIR", raising=False)
    monkeypatch.delenv("NEUROVA_SESSIONS_DIR", raising=False)
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    return data


def _seedLegacyAgent(data, agent_id: str, owner: str = "") -> None:
    dir_ = data / agent_id
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "agent_config.json").write_text(json.dumps({
        "agent_id": agent_id, "name": agent_id,
        "owner_user_id": owner, "workspace_path": str(dir_ / "workspaces"),
    }, ensure_ascii=False), encoding="utf-8")
    (dir_ / "sessions").mkdir(exist_ok=True)
    (dir_ / "sessions" / "session_s1_2026-01-01.json").write_text("{}", encoding="utf-8")
    reg = data / "agents" / "agents.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    raw = {}
    if reg.exists():
        raw = json.loads(reg.read_text(encoding="utf-8"))
    raw[agent_id] = {"name": agent_id}
    reg.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")


def test_v3_migration_moves_owned_agent_under_user_bucket(layout):
    _seedLegacyAgent(layout, "kai", owner="u1")
    report = migrate_agent_layout_v3()
    assert (layout / "agent" / "u1" / "kai" / "agent_config.json").exists()
    assert not (layout / "kai").exists(), "v2 目录迁走后不得残留"
    assert report["moved"]
    index = json.loads((layout / "agent" / "index.json").read_text(encoding="utf-8"))
    assert index["agents"]["kai"]["bucket"] == "u1"


def test_v3_migration_unowned_agent_goes_to_share(layout):
    _seedLegacyAgent(layout, "pub", owner="")
    migrate_agent_layout_v3()
    assert (layout / "agent" / "share" / "pub" / "agent_config.json").exists()
    index = json.loads((layout / "agent" / "index.json").read_text(encoding="utf-8"))
    assert index["agents"]["pub"]["bucket"] == "share"


def test_v3_migration_skips_loaded_agents(layout, monkeypatch):
    _seedLegacyAgent(layout, "busy", owner="u1")
    monkeypatch.setattr("neurova.api.endpoints.get_agent_instance", lambda aid: object())
    report = migrate_agent_layout_v3()
    assert (layout / "busy").exists(), "loaded agent 的目录不得搬走（句柄悬空）"
    assert report["pending"], "loaded agent 必须进 pending 报告"


def test_v3_migration_full_scan_writes_sentinel(layout):
    _seedLegacyAgent(layout, "kai", owner="u1")
    migrate_agent_layout_v3()
    assert v3_migration_done() is True


def test_v3_migration_scoped_scan_does_not_write_sentinel(layout):
    _seedLegacyAgent(layout, "kai", owner="u1")
    migrate_agent_layout_v3(agent_ids=["kai"])
    assert v3_migration_done() is False, "定向扫描（按属主）不代表全量切换完成"


def test_v3_migration_dry_run_moves_nothing(layout):
    _seedLegacyAgent(layout, "kai", owner="u1")
    report = migrate_agent_layout_v3(dry_run=True)
    assert (layout / "kai").exists(), "干跑不得搬移"
    assert report["moved"], "干跑仍要给出搬迁计划"


def test_v3_migration_idempotent(layout):
    _seedLegacyAgent(layout, "kai", owner="u1")
    migrate_agent_layout_v3()
    second = migrate_agent_layout_v3()
    assert second["counts"]["moved"] == 0
    assert (layout / "agent" / "u1" / "kai" / "agent_config.json").exists()


def test_v3_migration_conflict_keeps_both(layout):
    _seedLegacyAgent(layout, "kai", owner="u1")
    target = layout / "agent" / "u1" / "kai"
    target.mkdir(parents=True)
    (target / "extra.txt").write_text("x", encoding="utf-8")
    report = migrate_agent_layout_v3()
    assert report["conflicts"], "目标已存在必须报冲突（不覆盖）"
    assert (layout / "kai" / "agent_config.json").exists(), "源保留"
    assert (target / "extra.txt").exists(), "目标保留"


def test_ensure_skips_when_sentinel_present(layout):
    _seedLegacyAgent(layout, "kai", owner="u1")
    migrate_agent_layout_v3()
    again = ensure_agent_layout_v3()
    assert again.get("skipped") == "sentinel"
    assert v3_migration_done() is True


def test_ensure_runs_cutover_when_sentinel_absent(layout):
    _seedLegacyAgent(layout, "kai", owner="u1")
    report = ensure_agent_layout_v3()
    assert report["moved"]
    assert v3_migration_done() is True
