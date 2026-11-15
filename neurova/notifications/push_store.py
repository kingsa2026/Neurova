# -*- coding: utf-8 -*-
"""移动端推送令牌存储（SQLite，设计方案 §8.4 S-3）。

- 一用户多设备并存：upsert 键 = (device_id)，同一设备换 token 覆盖。
- 表结构纳入迁移域 "mobile_push"（core/db_migration.py，PRAGMA user_version），
  禁止只写 CREATE TABLE IF NOT EXISTS 而无迁移条目（AGENTS §3）。
- 推送令牌不是长期身份凭据：泄露只影响通知触达，不授权任何数据读取；
  但仍不入日志（打日志只记 device_id/platform）。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import List, Optional

from neurova.core.data_root import dataPath
from neurova.core.db_migration import migrate as apply_migrations, register_migration
from neurova.core.logger import get_logger

logger = get_logger(__name__)

_DB_PATH = dataPath("mobile_push.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mobile_push_tokens (
    device_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    push_token TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_push_tokens_user ON mobile_push_tokens(user_id);
"""

register_migration(1, _SCHEMA, domain="mobile_push")

_LOCK = threading.RLock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    apply_migrations(conn, domain="mobile_push")
    return conn


class PushTokenRecord:
    """一条设备推送令牌（行映射）。"""

    def __init__(self, row: sqlite3.Row):
        self.device_id: str = row["device_id"]
        self.user_id: str = row["user_id"]
        self.platform: str = row["platform"]
        self.push_token: str = row["push_token"]
        self.updated_at: float = float(row["updated_at"])


def upsert_token(user_id: str, platform: str, push_token: str, device_id: str) -> None:
    """上报/更新设备推送令牌（同设备覆盖，用户可变——设备换手后旧用户失效）。"""
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO mobile_push_tokens (device_id, user_id, platform, push_token, updated_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(device_id) DO UPDATE SET"
                " user_id=excluded.user_id, platform=excluded.platform,"
                " push_token=excluded.push_token, updated_at=excluded.updated_at",
                (device_id, user_id, platform, push_token, time.time()),
            )
            conn.commit()
        finally:
            conn.close()


def remove_token(device_id: str) -> bool:
    """注销设备令牌（登出/解绑）。返回是否确有删除。"""
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute("DELETE FROM mobile_push_tokens WHERE device_id = ?", (device_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def list_tokens_for_user(user_id: str) -> List[PushTokenRecord]:
    """取某用户的全部设备令牌（扇出用）。"""
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM mobile_push_tokens WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
            return [PushTokenRecord(r) for r in rows]
        finally:
            conn.close()


def db_path() -> Path:
    return Path(_DB_PATH)
