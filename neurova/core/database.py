"""
数据库连接管理
"""

from __future__ import annotations

import sqlite3
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_db_conn: Optional[sqlite3.Connection] = None

def _get_db_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    """获取数据库连接"""
    global _db_conn
    if _db_conn is None:
        path = db_path or "neurova.db"
        _db_conn = sqlite3.connect(path)
        _db_conn.row_factory = sqlite3.Row
    return _db_conn

def close_db_conn():
    """关闭数据库连接"""
    global _db_conn
    if _db_conn:
        _db_conn.close()
        _db_conn = None
