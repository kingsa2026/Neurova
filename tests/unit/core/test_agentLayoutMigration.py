# -*- coding: utf-8 -*-
"""旧 agent 扁平落点 → `data/<agent_id>/` 统一布局的一次性迁移判据。

迁移必须满足：
- 旧物搬净：`agent_workspaces/<id>`、`data/sessions/<id>`、`data/agents/<id>/*`
  等旧面全部收进 `<agent_root>/{workspaces,sessions,memory,skills,...}`；
- 不覆盖：新旧同名物同时存在时保留双方并报告冲突，绝不静默丢数据；
- 幂等：第二次执行不再移动任何东西；
- dry-run 只出计划、不落盘。
"""
import json
from pathlib import Path

import pytest

from neurova.agent_config import reset_config_manager
from neurova.core.agent_layout_migration import (
    auto_migrate_legacy_agent_layout,
    migrate_legacy_agent_layout,
)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("NEUROVA_AGENT_WORKSPACES_DIR", raising=False)
    monkeypatch.delenv("NEUROVA_SESSIONS_DIR", raising=False)
    reset_config_manager()
    yield tmp_path
    reset_config_manager()


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_legacy(env: Path, agent_id: str = "kai") -> Path:
    data = env / "data"
    legacy_ws = env / "legacy_ws"
    ws = legacy_ws / agent_id
    _write(ws / "agent_config.json", '{"name": "Kai"}')
    _write(ws / "memory" / "memory.db", "SQLITE")
    _write(ws / "memory" / "soul.md", "身份")
    _write(ws / "memory" / "muscle_memory" / "l1.json", "{}")
    _write(ws / "attachments" / "a.txt", "attachment")
    _write(ws / "knowledge_graph" / "nodes.json", "[]")
    _write(data / "sessions" / agent_id / "session_s1_2026-01-01.json", "{}")
    _write(data / "agents" / agent_id / "skills" / "manifest.json", "{}")
    _write(data / "agents" / agent_id / "proposals" / "p.json", "{}")
    _write(data / "agents" / agent_id / "evolution" / "runs" / "r.json", "{}")
    _write(data / "agents" / "souls" / agent_id / "soul.json", "{}")
    _write(data / "personality" / f"{agent_id}.json", "{}")
    _write(data / "sleep_settings" / f"{agent_id}.json", "{}")
    _write(data / "media_config" / f"{agent_id}.json", "{}")
    _write(data / "seen-cursors" / "agents" / f"{agent_id}.json", "{}")
    _write(data / "context_ledger" / f"{agent_id}.db", "SQLITE")
    _write(data / "checkpoints" / f"{agent_id}.git" / "HEAD", "ref")
    _write(data / "evolution" / "evidence" / agent_id / "skill" / "e.json", "{}")
    reset_config_manager()
    from neurova.agent_config import get_config_manager

    get_config_manager().create_agent(agent_id=agent_id, name="Kai")
    return legacy_ws


def test_moves_all_legacy_faces_into_agent_root(env):
    legacy_ws = _seed_legacy(env)
    data = env / "data"
    root = data / "kai"

    report = migrate_legacy_agent_layout(legacy_workspace_root=legacy_ws)

    assert not report["errors"], report
    assert (root / "agent_config.json").is_file()
    assert (root / "memory" / "memory.db").is_file()
    assert (root / "memory" / "muscle_memory" / "l1.json").is_file()
    assert (root / "soul.md").is_file()
    assert (root / "workspaces" / "attachments" / "a.txt").is_file()
    assert (root / "workspaces" / "knowledge_graph" / "nodes.json").is_file()
    assert (root / "sessions" / "session_s1_2026-01-01.json").is_file()
    assert (root / "skills" / "manifest.json").is_file()
    assert (root / "proposals" / "p.json").is_file()
    assert (root / "evolution" / "runs" / "r.json").is_file()
    assert (root / "evolution" / "evidence" / "skill" / "e.json").is_file()
    assert (root / "soul.json").is_file()
    assert (root / "personality.json").is_file()
    assert (root / "sleep_settings.json").is_file()
    assert (root / "media_config.json").is_file()
    assert (root / "seen_cursors.json").is_file()
    assert (root / "context_ledger.db").is_file()
    assert (root / "checkpoints.git" / "HEAD").is_file()
    assert not (legacy_ws / "kai" / "agent_config.json").exists()
    assert not (data / "sessions" / "kai").exists()
    assert not (data / "agents" / "kai").exists()
    assert not (data / "personality" / "kai.json").exists()


def test_second_run_is_idempotent(env):
    legacy_ws = _seed_legacy(env)
    migrate_legacy_agent_layout(legacy_workspace_root=legacy_ws)
    second = migrate_legacy_agent_layout(legacy_workspace_root=legacy_ws)
    assert second["moved"] == []
    assert second["errors"] == []


def test_conflict_keeps_both_sides_and_reports(env):
    legacy_ws = _seed_legacy(env)
    target = env / "data" / "kai" / "workspaces" / "attachments" / "a.txt"
    _write(target, "already-here")

    report = migrate_legacy_agent_layout(legacy_workspace_root=legacy_ws)

    assert target.read_text(encoding="utf-8") == "already-here"
    assert (legacy_ws / "kai" / "attachments" / "a.txt").read_text(encoding="utf-8") == "attachment"
    assert any(c["target"] == str(target) for c in report["conflicts"]), report


def test_dry_run_does_not_touch_disk(env):
    legacy_ws = _seed_legacy(env)
    report = migrate_legacy_agent_layout(legacy_workspace_root=legacy_ws, dry_run=True)
    assert report["moved"], report
    assert (legacy_ws / "kai" / "attachments" / "a.txt").exists()
    assert not (env / "data" / "kai" / "workspaces" / "attachments" / "a.txt").exists()


def test_report_written_for_apply(env):
    legacy_ws = _seed_legacy(env)
    migrate_legacy_agent_layout(legacy_workspace_root=legacy_ws)
    report_path = env / "data" / "agent_layout_migration.json"
    assert report_path.is_file()
    body = json.loads(report_path.read_text(encoding="utf-8"))
    assert body["moved"], body


def test_stored_absolute_paths_follow_the_move(env):
    """附件表/会话元数据里的绝对路径必须跟着搬，不能指向已失效的旧工作区。"""
    import sqlite3

    legacy_ws = _seed_legacy(env)
    old_attachment = legacy_ws / "kai" / "attachments" / "a.txt"
    db = legacy_ws / "kai" / "memory" / "memory.db"
    db.unlink()
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE attachments (id TEXT, file_path TEXT)")
    conn.execute("INSERT INTO attachments VALUES ('a1', ?)", (str(old_attachment),))
    conn.commit()
    conn.close()

    session = env / "data" / "sessions" / "kai" / "session_s1_2026-01-01.json"
    session.write_text(json.dumps({
        "agent_id": "kai", "session_id": "s1", "messages": [
            {"role": "assistant", "content": "x", "metadata": {"artifacts": [
                {"path": str(old_attachment)}
            ]}}
        ]
    }, ensure_ascii=False), encoding="utf-8")

    migrate_legacy_agent_layout(legacy_workspace_root=legacy_ws)

    new_attachment = env / "data" / "kai" / "workspaces" / "attachments" / "a.txt"
    conn = sqlite3.connect(env / "data" / "kai" / "memory" / "memory.db")
    stored = conn.execute("SELECT file_path FROM attachments").fetchone()[0]
    conn.close()
    assert stored == str(new_attachment)
    moved_session = json.loads(
        (env / "data" / "kai" / "sessions" / "session_s1_2026-01-01.json").read_text(encoding="utf-8")
    )
    assert moved_session["messages"][0]["metadata"]["artifacts"][0]["path"] == str(new_attachment)


def test_auto_migration_skips_injected_data_root(env):
    """测试/隔离数据根下启动不得搬仓库真实旧物。"""
    (env / "data").mkdir(parents=True, exist_ok=True)
    report = auto_migrate_legacy_agent_layout()
    assert report == {"skipped": "injected_data_root"}


def test_auto_migration_runs_on_default_data_root(monkeypatch):
    """数据根就是仓库 data/ 时才进入迁移器（用哨兵证明调用发生，不真搬）。"""
    import neurova.core.agent_layout_migration as mig

    called = {}
    monkeypatch.delenv("NEUROVA_DATA_DIR", raising=False)

    def _fake():
        called["ran"] = True
        return {"moved_count": 0}

    monkeypatch.setattr(mig, "migrate_legacy_agent_layout", _fake)
    assert auto_migrate_legacy_agent_layout() == {"moved_count": 0}
    assert called["ran"] is True
