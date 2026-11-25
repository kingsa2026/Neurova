# -*- coding: utf-8 -*-
"""agent 迁移包（zip）导出/导入判据。

锁定：
- 导出包含 `data/<agent_id>/` 全量 + 轨迹 + manifest；
- 导入后归属全部改为导入者（agent/会话/记忆/轨迹/配置）；
- 目标 ID 冲突 409，覆盖仅 admin；
- 覆盖失败原路恢复旧数据；
- zip slip 拒绝。
"""
from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import neurova.api.endpoints.agent_package as package_api
from neurova.agent_config import reset_config_manager
from neurova.api.endpoints import set_app_state
from neurova.session_manager import SessionManager


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fake_agent(agent_id: str, owner: str = "u1"):
    root = Path(__import__("os").environ["NEUROVA_DATA_DIR"]) / agent_id
    return SimpleNamespace(
        config=SimpleNamespace(
            agent_id=agent_id,
            name="PackAgent",
            description="exported",
            workspace_path=str(root / "workspaces"),
            owner_user_id=owner,
            llm_config=SimpleNamespace(model="gpt-4"),
            llm_provider="openai",
            personality="",
            constitution="",
        )
    )


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("NEUROVA_AGENT_WORKSPACES_DIR", raising=False)
    monkeypatch.delenv("NEUROVA_SESSIONS_DIR", raising=False)
    monkeypatch.setattr(
        package_api, "_SkillService",
        lambda agent_id: SimpleNamespace(list_skills=lambda: []),
    )
    monkeypatch.setattr(package_api, "_list_scheduler_tasks", lambda: [])
    monkeypatch.setattr(package_api, "_list_mcp_servers", lambda: [])
    reset_config_manager()
    SessionManager._instance = None
    set_app_state(None)
    yield tmp_path
    set_app_state(None)
    reset_config_manager()
    SessionManager._instance = None


@pytest.fixture()
def client(env):
    from neurova.api.auth import get_current_user
    from neurova.api.endpoints import agent_migration

    app = FastAPI()
    app.include_router(package_api.router, prefix="/v1/agents")
    app.include_router(agent_migration.router, prefix="/v1/agents")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1", "username": "u1", "role": "admin", "neuser_id": "u1",
    }
    return TestClient(app)


def _seed_agent(env: Path, agent_id: str = "packa") -> Path:
    data = env / "data"
    root = data / agent_id
    _write(root / "agent_config.json", json.dumps({
        "name": "PackAgent", "model": "gpt-4", "provider": "openai",
        "owner_user_id": "u1", "temperature": 0.7,
    }, ensure_ascii=False))
    _write(root / "workspaces" / "attachments" / "a.txt", "attachment")
    _write(root / "skills" / "manifest.json", "{}")
    _write(root / "personality.json", '{"traits": {}}')
    _write(root / "checkpoints.git" / "HEAD", "ref")
    _write(root / "sessions" / "session_s1_2026-01-01.json", json.dumps({
        "agent_id": agent_id, "session_id": "s1", "user_id": "alice",
        "title": "迁移会话", "messages": [],
    }, ensure_ascii=False))
    db = root / "memory" / "memory.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT, agent_id TEXT, neuser_id TEXT, user_id TEXT)"
    )
    conn.execute(
        "INSERT INTO memories VALUES ('m1', 'remember me', ?, 'alice', 'alice')",
        (agent_id,),
    )
    conn.commit()
    conn.close()
    _write(data / "trajectories" / "alice" / agent_id / "t1.json", json.dumps({
        "trace_id": "t1", "agent_id": agent_id, "user_id": "alice", "session_id": "s1",
    }, ensure_ascii=False))
    set_app_state({"agents": {agent_id: _fake_agent(agent_id)}})
    return root


def _export(client, agent_id: str = "packa") -> bytes:
    resp = client.get(f"/v1/agents/{agent_id}/export-migration")
    assert resp.status_code == 200, resp.text
    return resp.content


def _import(client, package: bytes, *, agent_id: str = "newname", overwrite: bool = False):
    return client.post(
        "/v1/agents/import-migration",
        files={"file": ("package.zip", package, "application/zip")},
        data={
            "agent_id": agent_id,
            "overwrite": "true" if overwrite else "false",
            "import_skills": "false",
            "import_cron": "false",
            "import_mcp": "false",
        },
    )


def test_export_contains_manifest_agent_and_trajectories(env, client):
    _seed_agent(env)
    package = _export(client)
    with zipfile.ZipFile(__import__("io").BytesIO(package)) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["kind"] == "neurova.agent-migration"
    assert manifest["manifest_version"] == 1
    assert manifest["source"]["agent_id"] == "packa"
    assert "agent/agent_config.json" in names
    assert "agent/memory/memory.db" in names
    assert "agent/sessions/session_s1_2026-01-01.json" in names
    assert "trajectories/alice/t1.json" in names


def test_import_rewrites_all_ownership_to_importer(env, client, monkeypatch):
    _seed_agent(env)
    package = _export(client)
    set_app_state({"agents": {}})

    class _FakeRuntime:
        def __init__(self, config):
            self.config = config

    monkeypatch.setattr("neurova.agent_core.Agent", _FakeRuntime)

    resp = _import(client, package, agent_id="newname")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["owner_user_id"] == "u1"
    assert body["source_agent_id"] == "packa"

    data = env / "data"
    root = data / "newname"
    cfg = json.loads((root / "agent_config.json").read_text(encoding="utf-8"))
    assert cfg["owner_user_id"] == "u1"

    conn = sqlite3.connect(root / "memory" / "memory.db")
    row = conn.execute("SELECT agent_id, neuser_id, user_id FROM memories").fetchone()
    conn.close()
    assert row == ("newname", "u1", "u1")

    session = json.loads(
        (root / "sessions" / "session_s1_2026-01-01.json").read_text(encoding="utf-8")
    )
    assert session["agent_id"] == "newname"
    assert session["user_id"] == "u1"

    trace = json.loads(
        (data / "trajectories" / "u1" / "newname" / "t1.json").read_text(encoding="utf-8")
    )
    assert trace["agent_id"] == "newname"
    assert trace["user_id"] == "u1"

    from neurova.agent_config import get_config_manager

    assert get_config_manager().get_agent("newname")["owner_user_id"] == "u1"


def test_import_conflict_409(env, client, monkeypatch):
    _seed_agent(env)
    package = _export(client)
    monkeypatch.setattr("neurova.agent_core.Agent", lambda config: SimpleNamespace(config=config))
    assert _import(client, package, agent_id="newname").status_code == 200
    assert _import(client, package, agent_id="newname").status_code == 409


def test_overwrite_requires_admin(env, client, monkeypatch):
    _seed_agent(env)
    package = _export(client)
    monkeypatch.setattr("neurova.agent_core.Agent", lambda config: SimpleNamespace(config=config))
    from neurova.api.auth import get_current_user

    client.app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u2", "username": "u2", "role": "user", "neuser_id": "u2",
    }
    resp = _import(client, package, agent_id="packa", overwrite=True)
    assert resp.status_code == 403


def test_overwrite_failure_restores_old_data(env, client, monkeypatch):
    _seed_agent(env)
    package = _export(client)
    target = env / "data" / "packa"
    marker = target / "OLD_MARKER.txt"
    _write(marker, "old")

    def _boom(*a, **kw):
        raise RuntimeError("build failed")

    monkeypatch.setattr("neurova.agent_migration._buildAgentConfig", _boom)
    resp = _import(client, package, agent_id="packa", overwrite=True)
    assert resp.status_code == 500
    assert marker.read_text(encoding="utf-8") == "old"


# ── CORE-05：回滚不得在"新目标未删净"时销毁旧数据备份 ──────────────────

def _restoreScene(tmp_path: Path):
    """构造回滚现场：旧 agent 数据已移入备份目录。"""
    from neurova.agent_migration import PreparedImport

    base = tmp_path / "data"
    backup_parent = base / ".nvmig-backup-tok123"
    old_dir = backup_parent / "packb"
    old_dir.mkdir(parents=True)
    (old_dir / "OLD_MARKER.txt").write_text("old-data", encoding="utf-8")
    prepared = PreparedImport(
        manifest={}, source_id="packa", target_id="packb", importer="u1",
        overwrite=True, stage_dir=tmp_path / "stage",
        target_root=base / "packb", target_trajectory_dir=base / "traj" / "packb",
        source_paths={}, trajectory_sources={}, registry_entry=None,
    )
    prepared.backup_dirs.append(backup_parent)
    return prepared, backup_parent, old_dir


def test_rollbackKeepsBackupWhenTargetStillOccupied(tmp_path):
    """原位仍被（删不净的）新目标占着时，恢复必须报错并保留备份。

    缺陷形态：跳过恢复 → 无条件 rmtree 备份 → 旧数据唯一副本被销毁。
    """
    from neurova.agent_migration import MigrationError, _restoreBackup

    prepared, backup_parent, old_dir = _restoreScene(tmp_path)
    prepared.target_root.mkdir(parents=True)
    (prepared.target_root / "NEW_MARKER.txt").write_text("new-data", encoding="utf-8")

    with pytest.raises(MigrationError):
        _restoreBackup(prepared)

    assert (old_dir / "OLD_MARKER.txt").read_text(encoding="utf-8") == "old-data", \
        "恢复失败后旧备份被删——三重丢失"


def test_rollbackFailureSurvivesDiscardPrepared(tmp_path):
    """恢复失败的备份必须活过 discard_prepared（失败路径的兜底清理不得销毁它）。"""
    from neurova.agent_migration import _restoreBackup, discard_prepared

    prepared, backup_parent, old_dir = _restoreScene(tmp_path)
    prepared.target_root.mkdir(parents=True)

    with pytest.raises(Exception):
        _restoreBackup(prepared)
    discard_prepared(prepared)
    assert (old_dir / "OLD_MARKER.txt").exists(), "discard_prepared 把恢复失败的备份删了"


def test_rollbackStillRestoresAndCleansOnHappyPath(tmp_path):
    """对照：原位已腾空时，恢复照旧移回旧数据并清掉备份目录（不因修复而退化）。"""
    from neurova.agent_migration import _restoreBackup

    prepared, backup_parent, old_dir = _restoreScene(tmp_path)
    _restoreBackup(prepared)
    assert (prepared.target_root / "OLD_MARKER.txt").read_text(encoding="utf-8") == "old-data"
    assert not backup_parent.exists(), "恢复成功后备份目录应被清理"


def test_overwriteFailureWithStuckTargetKeepsBackup(env, client, monkeypatch):
    """端到端：新目标删不净（文件占用/权限）时，回滚保留旧数据备份并如实报失败。"""
    _seed_agent(env)
    package = _export(client)
    _write(env / "data" / "packa" / "OLD_MARKER.txt", "old")

    def _boom(*a, **kw):
        raise RuntimeError("build failed")

    monkeypatch.setattr("neurova.agent_migration._buildAgentConfig", _boom)
    # 模拟文件占用：placed 的新目标删不掉（_removePath 失败且不再静默吞掉）
    monkeypatch.setattr("neurova.agent_migration._removePath", lambda p: False)
    resp = _import(client, package, agent_id="packa", overwrite=True)
    assert resp.status_code == 500
    backups = list((env / "data").glob(".nvmig-backup-*/packa/OLD_MARKER.txt"))
    assert backups, "回滚恢复失败后旧数据备份被删——数据三重丢失"
    assert backups[0].read_text(encoding="utf-8") == "old"


def test_zip_slip_rejected(env, client):
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "kind": "neurova.agent-migration", "manifest_version": 1,
            "source": {"agent_id": "packa"}, "agent": {"name": "X"},
        }))
        zf.writestr("../evil.txt", "pwned")
    resp = _import(client, buf.getvalue(), agent_id="newname")
    assert resp.status_code == 422
    assert not (env / "evil.txt").exists()
