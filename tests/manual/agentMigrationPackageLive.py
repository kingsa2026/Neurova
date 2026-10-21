# -*- coding: utf-8 -*-
"""agent 迁移包活体验证：真 create_app + 真 Agent，导出 → 导入新 ID → 归属改写。

只写临时数据根；不碰仓库 data/ 与 agent_workspaces/。
运行：
    PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe tests/manual/agentMigrationPackageLive.py
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

_ok = 0
_fail = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global _ok, _fail
    if condition:
        _ok += 1
        print(f"PASS {name}")
    else:
        _fail += 1
        print(f"FAIL {name} {detail}")


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _agent_ids(response) -> set:
    body = response.json()
    items = body if isinstance(body, list) else (body.get("data") or body.get("agents") or [])
    if isinstance(items, dict):
        items = items.get("agents") or items.get("items") or []
    return {a.get("id") or a.get("agent_id") for a in items if isinstance(a, dict)}


def main() -> int:
    data_root = Path(tempfile.mkdtemp(prefix="nvmig-pkg-live-"))
    os.environ["NEUROVA_DATA_DIR"] = str(data_root)
    os.environ.pop("NEUROVA_AGENT_WORKSPACES_DIR", None)
    os.environ.pop("NEUROVA_SESSIONS_DIR", None)

    source = "packa"
    root = data_root / source
    _write(root / "agent_config.json", json.dumps({
        "name": "PackAgent", "model": "gpt-4", "provider": "openai",
        "owner_user_id": "admin", "description": "live",
    }, ensure_ascii=False))
    _write(root / "workspaces" / "attachments" / "a.txt", "attachment")
    _write(root / "skills" / "manifest.json", "{}")
    _write(root / "sessions" / "session_s1_2026-01-01.json", json.dumps({
        "agent_id": source, "session_id": "s1", "user_id": "alice",
        "title": "迁移会话", "messages": [],
    }, ensure_ascii=False))
    probe_db = root / "memory" / "ownership_probe.db"
    probe_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(probe_db)
    conn.execute("CREATE TABLE memories (id TEXT, agent_id TEXT, user_id TEXT, neuser_id TEXT)")
    conn.execute("INSERT INTO memories VALUES ('m1', ?, 'alice', 'alice')", (source,))
    conn.commit()
    conn.close()
    _write(data_root / "trajectories" / "alice" / source / "t1.json", json.dumps({
        "trace_id": "t1", "agent_id": source, "user_id": "alice", "session_id": "s1",
    }, ensure_ascii=False))

    from neurova.agent_config import reset_config_manager
    from neurova.api.endpoints import set_app_state
    from neurova.session_manager import SessionManager

    reset_config_manager()
    SessionManager._instance = None
    set_app_state(None)

    try:
        from fastapi.testclient import TestClient

        from neurova.api.app import create_app
        from neurova.api.auth import create_access_token

        app = create_app()
        token = create_access_token({"sub": "importer", "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app) as client:
            resp = client.get("/api/v1/agents", headers=headers)
            ids = _agent_ids(resp)
            check("源 agent 已加载", source in ids, str(ids))

            exported = client.get(f"/api/v1/agents/{source}/export-migration", headers=headers)
            check("导出 200 zip", exported.status_code == 200 and exported.content[:2] == b"PK",
                  f"{exported.status_code}")
            with zipfile.ZipFile(io.BytesIO(exported.content)) as zf:
                names = set(zf.namelist())
                manifest = json.loads(zf.read("manifest.json"))
            check("包含 manifest/agent/轨迹", "manifest.json" in names
                  and "agent/agent_config.json" in names
                  and "trajectories/alice/t1.json" in names, str(sorted(names)[:6]))
            check("manifest 来源正确", manifest["source"]["agent_id"] == source)

            imported = client.post(
                "/api/v1/agents/import-migration",
                headers=headers,
                files={"file": ("package.zip", exported.content, "application/zip")},
                data={
                    "agent_id": "newname", "overwrite": "false",
                    "import_skills": "false", "import_cron": "false", "import_mcp": "false",
                },
            )
            check("导入 200", imported.status_code == 200, f"{imported.status_code} {imported.text[:200]}")
            body = imported.json()
            check("归属=导入者", body.get("owner_user_id") == "importer", str(body))

            target = data_root / "newname"
            cfg = json.loads((target / "agent_config.json").read_text(encoding="utf-8"))
            check("配置属主改写", cfg.get("owner_user_id") == "importer", str(cfg))
            session = json.loads(
                (target / "sessions" / "session_s1_2026-01-01.json").read_text(encoding="utf-8")
            )
            check("会话归属改写", session.get("user_id") == "importer" and session.get("agent_id") == "newname",
                  str(session))
            conn = sqlite3.connect(target / "memory" / "ownership_probe.db")
            row = conn.execute("SELECT agent_id, user_id, neuser_id FROM memories").fetchone()
            conn.close()
            check("记忆归属改写", row == ("newname", "importer", "importer"), str(row))
            trace = json.loads(
                (data_root / "trajectories" / "importer" / "newname" / "t1.json").read_text(encoding="utf-8")
            )
            check("轨迹归属改写", trace.get("agent_id") == "newname" and trace.get("user_id") == "importer",
                  str(trace))

            listed = client.get("/api/v1/agents", headers=headers)
            ids = _agent_ids(listed)
            check("导入后的 agent 运行时可见", "newname" in ids, str(ids))

            overwritten = client.post(
                "/api/v1/agents/import-migration",
                headers=headers,
                files={"file": ("package.zip", exported.content, "application/zip")},
                data={
                    "agent_id": "newname", "overwrite": "true",
                    "import_skills": "false", "import_cron": "false", "import_mcp": "false",
                },
            )
            check("admin 覆盖导入 200", overwritten.status_code == 200,
                  f"{overwritten.status_code} {overwritten.text[:200]}")
    except Exception as e:  # noqa: BLE001
        check("活体链路", False, f"{type(e).__name__}: {e}")

    try:
        shutil.rmtree(data_root)
    except OSError:
        pass
    print(f"\n结果：{_ok} passed, {_fail} failed")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
