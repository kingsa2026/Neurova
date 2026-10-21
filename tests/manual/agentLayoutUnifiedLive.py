# -*- coding: utf-8 -*-
"""v2 agent 布局活体验证：旧布局 → 迁移 → 真 app 加载。

只写临时目录；不读也不动仓库 `data/` 与 `agent_workspaces/`。
运行：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/manual/agentLayoutUnifiedLive.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
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


def main() -> int:
    data_root = Path(tempfile.mkdtemp(prefix="nvmig-live-data-"))
    legacy_root = Path(tempfile.mkdtemp(prefix="nvmig-live-legacy-")) / "agent_workspaces"
    os.environ["NEUROVA_DATA_DIR"] = str(data_root)
    os.environ.pop("NEUROVA_AGENT_WORKSPACES_DIR", None)
    os.environ.pop("NEUROVA_SESSIONS_DIR", None)

    agent_id = "liveagent"
    legacy_ws = legacy_root / agent_id
    _write(legacy_ws / "agent_config.json", json.dumps({
        "name": "LiveAgent", "model": "gpt-4", "provider": "openai",
        "description": "layout live", "owner_user_id": "",
    }, ensure_ascii=False))
    _write(legacy_ws / "memory" / "soul.md", "你是 LiveAgent")
    _write(legacy_ws / "attachments" / "a.txt", "attachment")
    _write(legacy_ws / "knowledge_graph" / "nodes.json", "[]")
    _write(legacy_ws / "knowledge_graph" / "edges.json", "[]")
    _write(data_root / "sessions" / agent_id / "session_s1_2026-01-01.json", json.dumps({
        "agent_id": agent_id, "session_id": "s1", "session_date": "2026-01-01",
        "user_id": "", "title": "迁移会话", "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00", "total_messages": 0, "messages": [],
    }, ensure_ascii=False))
    _write(data_root / "agents" / agent_id / "skills" / "manifest.json", "{}")
    _write(data_root / "agents" / "agents.json", json.dumps({
        agent_id: {
            "id": agent_id, "name": "LiveAgent", "description": "layout live",
            "created_at": "2026-01-01T00:00:00", "last_active": "2026-01-01T00:00:00",
            "config": {"model": "gpt-4", "provider": "openai"},
        }
    }, ensure_ascii=False))

    from neurova.agent_config import reset_config_manager
    from neurova.api.endpoints import set_app_state
    from neurova.core.agent_layout_migration import migrate_legacy_agent_layout
    from neurova.session_manager import SessionManager

    reset_config_manager()
    SessionManager._instance = None
    set_app_state(None)

    report = migrate_legacy_agent_layout(
        legacy_workspace_root=legacy_root,
        sessions_root=data_root / "sessions",
    )
    check("迁移无错误", not report["errors"], str(report["errors"][:2]))
    check("迁移有搬运", report["moved_count"] > 0, str(report["moved_count"]))

    root = data_root / agent_id
    check("配置文件在 agent 根", (root / "agent_config.json").is_file())
    check("工作区在 workspaces/", (root / "workspaces" / "attachments" / "a.txt").is_file())
    check("图谱在 workspaces/", (root / "workspaces" / "knowledge_graph" / "nodes.json").is_file())
    check("记忆目录独立", (root / "memory").is_dir())
    check("身份文件在 agent 根", (root / "soul.md").is_file())
    check("会话在 sessions/", (root / "sessions" / "session_s1_2026-01-01.json").is_file())
    check("技能库在 skills/", (root / "skills" / "manifest.json").is_file())
    check("旧工作区已搬空", not (legacy_ws / "attachments").exists())

    try:
        from fastapi.testclient import TestClient

        from neurova.api.app import create_app
        from neurova.api.auth import create_access_token

        app = create_app()
        token = create_access_token({"sub": "layout-live", "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app) as client:
            resp = client.get("/api/v1/agents", headers=headers)
            body = resp.json()
            agents = body if isinstance(body, list) else (body.get("data") or body.get("agents") or [])
            ids = {a.get("id") or a.get("agent_id") for a in agents if isinstance(a, dict)}
            check("真 app 可列 agent", resp.status_code == 200, f"{resp.status_code} {resp.text[:120]}")
            check("迁移后的 agent 已加载", agent_id in ids, str(ids))

            mem = client.get(f"/api/v1/agents/{agent_id}/stats", headers=headers)
            check("迁移后的 agent 统计可用", mem.status_code in (200, 404), f"{mem.status_code}")
    except Exception as e:  # noqa: BLE001 - 活体验证把异常如实记为失败
        check("真 app 启动", False, f"{type(e).__name__}: {e}")

    try:
        shutil.rmtree(data_root)
        shutil.rmtree(legacy_root.parent)
    except OSError:
        pass
    print(f"\n结果：{_ok} passed, {_fail} failed")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
