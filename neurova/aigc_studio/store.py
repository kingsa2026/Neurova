# -*- coding: utf-8 -*-
"""aigc_studio 存储层（R3）：SQLite WAL + 属主隔离。

实现自研），按复用裁剪为 9 表
服务商配置复用 Neurova provider 管理、任务队列复用 task_ledger、
关联关系（角色/道具 ↔ 集/分镜）以 JSON 数组列承载而非 link 表（本地单库形态）。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "aigc_studio.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(
  id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL, description TEXT DEFAULT '', genre TEXT DEFAULT '',
  style TEXT DEFAULT '', aspect_ratio TEXT DEFAULT '9:16',
  total_episodes INTEGER DEFAULT 1, status TEXT DEFAULT 'draft',
  thumbnail TEXT DEFAULT '',
  created_at REAL, updated_at REAL, deleted_at REAL
);
CREATE TABLE IF NOT EXISTS episodes(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
  number INTEGER DEFAULT 1, title TEXT DEFAULT '', content TEXT DEFAULT '',
  synopsis TEXT DEFAULT '', status TEXT DEFAULT 'draft', duration REAL DEFAULT 0,
  video_path TEXT DEFAULT '', subtitle_path TEXT DEFAULT '',
  created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS characters(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
  name TEXT NOT NULL, role TEXT DEFAULT '', description TEXT DEFAULT '',
  appearance TEXT DEFAULT '', styling TEXT DEFAULT '', personality TEXT DEFAULT '',
  final_prompt TEXT DEFAULT '', image_path TEXT DEFAULT '', seed_value TEXT DEFAULT '',
  status TEXT DEFAULT 'pending', created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS scenes(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, episode_id TEXT DEFAULT '',
  location TEXT DEFAULT '', time TEXT DEFAULT '', prompt TEXT DEFAULT '',
  lighting TEXT DEFAULT '', final_prompt TEXT DEFAULT '', image_path TEXT DEFAULT '',
  status TEXT DEFAULT 'pending', created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS props(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
  name TEXT DEFAULT '', description TEXT DEFAULT '', final_prompt TEXT DEFAULT '',
  image_path TEXT DEFAULT '', status TEXT DEFAULT 'pending',
  created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS storyboards(
  id TEXT PRIMARY KEY, episode_id TEXT NOT NULL, scene_id TEXT DEFAULT '',
  number INTEGER DEFAULT 1, title TEXT DEFAULT '', description TEXT DEFAULT '',
  image_prompt TEXT DEFAULT '', video_prompt TEXT DEFAULT '',
  narration TEXT DEFAULT '', camera TEXT DEFAULT '', movement TEXT DEFAULT '',
  atmosphere TEXT DEFAULT '', bgm_prompt TEXT DEFAULT '', sound_effect TEXT DEFAULT '',
  duration REAL DEFAULT 3,
  characters_json TEXT DEFAULT '[]', props_json TEXT DEFAULT '[]',
  first_frame_path TEXT DEFAULT '', end_frame_path TEXT DEFAULT '',
  injected_prompt TEXT DEFAULT '',
  video_path TEXT DEFAULT '', video_status TEXT DEFAULT 'pending',
  ledger_task_id TEXT DEFAULT '', subtitle_path TEXT DEFAULT '',
  audio_path TEXT DEFAULT '',
  status TEXT DEFAULT 'pending', error TEXT DEFAULT '',
  created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS assets(
  id TEXT PRIMARY KEY, project_id TEXT DEFAULT '', kind TEXT NOT NULL,
  name TEXT DEFAULT '', ref_path TEXT DEFAULT '', meta_json TEXT DEFAULT '{}',
  created_at REAL
);
CREATE TABLE IF NOT EXISTS merges(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, episode_id TEXT NOT NULL,
  mode TEXT DEFAULT '', status TEXT DEFAULT 'pending',
  output_path TEXT DEFAULT '', output_url TEXT DEFAULT '', error TEXT DEFAULT '',
  warning TEXT DEFAULT '',
  items_json TEXT DEFAULT '[]', created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS runs(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL,
  status TEXT DEFAULT 'running', detail_json TEXT DEFAULT '{}', error TEXT DEFAULT '',
  created_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_ep_project ON episodes(project_id);
CREATE INDEX IF NOT EXISTS idx_sb_episode ON storyboards(episode_id);
CREATE INDEX IF NOT EXISTS idx_owner ON projects(owner_user_id);
"""

_TABLES = {
    "projects", "episodes", "characters", "scenes", "props",
    "storyboards", "assets", "merges", "runs",
}


def _now() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class StudioStore:
    """aigc_studio SQLite 存储（线程安全 + WAL，风格与 task_ledger/neurflow 一致）。"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path or DEFAULT_DB_PATH)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        # A1/A5：既有库幂等补列（旧版表缺新列——PRAGMA 探测，
        # 不依赖异常吞 duplicate：重复执行安全）
        for table, col in (("storyboards", "end_frame_path"), ("merges", "warning")):
            cols = {r["name"] for r in self._conn.execute(
                f"PRAGMA table_info({table})").fetchall()}
            if col not in cols:
                self._conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {col} TEXT DEFAULT ''")
                self._conn.commit()

    # ── 内部 ────────────────────────────────────────────────────────────

    def _insert(self, table: str, prefix: str, data: Dict[str, Any],
                id_: Optional[str] = None) -> Dict[str, Any]:
        assert table in _TABLES
        row = {"id": id_ or _new_id(prefix), **data,
               "created_at": _now(), "updated_at": _now()}
        cols = self._columns(table)
        row = {k: v for k, v in row.items() if k in cols}
        with self._lock:
            self._conn.execute(
                f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' * len(row))})",
                list(row.values()))
            self._conn.commit()
        return self._fetch_one(f"SELECT * FROM {table} WHERE id=?", (row["id"],))

    def _update(self, table: str, id_: str, fields: Dict[str, Any]) -> None:
        cols = self._columns(table) - {"id"}
        sets = {k: v for k, v in fields.items() if k in cols}
        if not sets:
            return
        sets["updated_at"] = _now()
        with self._lock:
            self._conn.execute(
                f"UPDATE {table} SET {','.join(k + '=?' for k in sets)} WHERE id=?",
                list(sets.values()) + [id_])
            self._conn.commit()

    def _columns(self, table: str) -> set:
        with self._lock:
            rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {r["name"] for r in rows}

    def _fetch_one(self, sql: str, args=()) -> Optional[Dict[str, Any]]:
        with self._lock:
            r = self._conn.execute(sql, args).fetchone()
        return dict(r) if r else None

    def _fetch_all(self, sql: str, args=()) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    # ── projects（属主隔离）─────────────────────────────────────────────

    def create_project(self, owner_user_id: str, **fields: Any) -> Dict[str, Any]:
        return self._insert("projects", "proj", {"owner_user_id": owner_user_id, **fields})

    def get_project(self, pid: str, user_id: str, is_admin: bool = False) -> Optional[Dict[str, Any]]:
        row = self._fetch_one("SELECT * FROM projects WHERE id=? AND deleted_at IS NULL", (pid,))
        if not row:
            return None
        if is_admin or row["owner_user_id"] == user_id:
            return row
        return None  # deny 与不存在同构（neurflow _owned_workflow_or_404 口径）

    def list_projects(self, user_id: str, is_admin: bool = False) -> List[Dict[str, Any]]:
        if is_admin:
            return self._fetch_all(
                "SELECT * FROM projects WHERE deleted_at IS NULL ORDER BY created_at DESC")
        return self._fetch_all(
            "SELECT * FROM projects WHERE deleted_at IS NULL AND owner_user_id=?"
            " ORDER BY created_at DESC", (user_id,))

    def update_project(self, pid: str, user_id: str, fields: Dict[str, Any],
                       is_admin: bool = False) -> bool:
        if self.get_project(pid, user_id, is_admin) is None:
            return False
        self._update("projects", pid, fields)
        return True

    def soft_delete(self, pid: str, user_id: str, is_admin: bool = False) -> bool:
        if self.get_project(pid, user_id, is_admin) is None:
            return False
        self._update("projects", pid, {"deleted_at": _now()})
        return True

    # ── episodes ────────────────────────────────────────────────────────

    def add_episode(self, pid: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._insert("episodes", "ep", {"project_id": pid, **data})

    def get_episode(self, eid: str) -> Optional[Dict[str, Any]]:
        return self._fetch_one("SELECT * FROM episodes WHERE id=?", (eid,))

    def list_episodes(self, pid: str) -> List[Dict[str, Any]]:
        return self._fetch_all("SELECT * FROM episodes WHERE project_id=? ORDER BY number", (pid,))

    def update_episode(self, eid: str, fields: Dict[str, Any]) -> None:
        self._update("episodes", eid, fields)

    # ── assets：characters / scenes / props ─────────────────────────────

    def add_character(self, pid: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._insert("characters", "chr", {"project_id": pid, **data})

    def list_characters(self, pid: str) -> List[Dict[str, Any]]:
        return self._fetch_all("SELECT * FROM characters WHERE project_id=?", (pid,))

    def add_scene(self, pid: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._insert("scenes", "scn", {"project_id": pid, **data})

    def list_scenes(self, pid: str) -> List[Dict[str, Any]]:
        return self._fetch_all("SELECT * FROM scenes WHERE project_id=?", (pid,))

    def add_prop(self, pid: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._insert("props", "prp", {"project_id": pid, **data})

    def list_props(self, pid: str) -> List[Dict[str, Any]]:
        return self._fetch_all("SELECT * FROM props WHERE project_id=?", (pid,))

    def get_asset_row(self, table: str, asset_id: str) -> Optional[Dict[str, Any]]:
        assert table in ("characters", "scenes", "props")
        return self._fetch_one(f"SELECT * FROM {table} WHERE id=?", (asset_id,))

    def update_asset_row(self, table: str, asset_id: str, fields: Dict[str, Any]) -> None:
        assert table in ("characters", "scenes", "props")
        self._update(table, asset_id, fields)

    # ── storyboards ─────────────────────────────────────────────────────

    def add_storyboard(self, eid: str, data: Dict[str, Any]) -> Dict[str, Any]:
        row = dict(data)
        if isinstance(row.get("characters"), (list, tuple)):
            row["characters_json"] = json.dumps(list(row.pop("characters")), ensure_ascii=False)
        if isinstance(row.get("props"), (list, tuple)):
            row["props_json"] = json.dumps(list(row.pop("props")), ensure_ascii=False)
        return self._insert("storyboards", "sb", {"episode_id": eid, **row})

    def get_storyboard(self, sid: str) -> Optional[Dict[str, Any]]:
        return self._fetch_one("SELECT * FROM storyboards WHERE id=?", (sid,))

    def list_storyboards(self, eid: str) -> List[Dict[str, Any]]:
        return self._fetch_all(
            "SELECT * FROM storyboards WHERE episode_id=? ORDER BY number", (eid,))

    def update_storyboard(self, sid: str, fields: Dict[str, Any]) -> None:
        row = dict(fields)
        if "characters" in row:
            row["characters_json"] = json.dumps(row.pop("characters") or [], ensure_ascii=False)
        if "props" in row:
            row["props_json"] = json.dumps(row.pop("props") or [], ensure_ascii=False)
        self._update("storyboards", sid, row)

    # ── assets 库 / merges / runs ───────────────────────────────────────

    def add_asset(self, data: Dict[str, Any]) -> Dict[str, Any]:
        row = dict(data)
        if "meta" in row:
            row["meta_json"] = json.dumps(row.pop("meta") or {}, ensure_ascii=False)
        return self._insert("assets", "ast", row)

    def list_assets(self, pid: str = "") -> List[Dict[str, Any]]:
        if pid:
            return self._fetch_all(
                "SELECT * FROM assets WHERE project_id=? OR project_id='' ORDER BY created_at DESC",
                (pid,))
        return self._fetch_all("SELECT * FROM assets ORDER BY created_at DESC")

    def add_merge(self, data: Dict[str, Any]) -> Dict[str, Any]:
        row = dict(data)
        if "items" in row:
            row["items_json"] = json.dumps(row.pop("items") or [], ensure_ascii=False)
        return self._insert("merges", "mrg", row)

    def get_merge(self, mid: str) -> Optional[Dict[str, Any]]:
        return self._fetch_one("SELECT * FROM merges WHERE id=?", (mid,))

    def update_merge(self, mid: str, fields: Dict[str, Any]) -> None:
        self._update("merges", mid, fields)

    def add_run(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._insert("runs", "run", data)

    def update_run(self, rid: str, fields: Dict[str, Any]) -> None:
        self._update("runs", rid, fields)

    def list_runs(self, pid: str) -> List[Dict[str, Any]]:
        return self._fetch_all(
            "SELECT * FROM runs WHERE project_id=? ORDER BY created_at DESC", (pid,))

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_store: Optional[StudioStore] = None
_store_lock = threading.Lock()


def get_store() -> StudioStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = StudioStore()
    return _store


def reset_store() -> None:
    global _store
    with _store_lock:
        if _store is not None:
            try:
                _store.close()
            except Exception:  # noqa: BLE001
                pass
        _store = None
