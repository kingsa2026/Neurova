"""交互式记忆写入待确认中间态（P1-2，Utopia pending_facts 裁剪版）。

设计（docs/Neurova_Utopia代码级对比_2026-09-04.md §2.3）：
- 独立 SQLite（与主记忆库分库）——失败方向：漏读 pending 的后果是
  "待审队列看不见"，不是"未确认记忆混进主库检索"（与 Utopia 0018
  把 pending_facts 独立成表同理：忘读的代价方向必须选错的那头）；
- 拒绝过的内容记指纹（归一化 sha256），同内容不再被重复提议
  （Utopia rejected_facts 同理）；
- confirm 经注入的 remember_fn 真正落库——本模块不依赖 MemoryManager，
  依赖方向是调用方（API/执行器）注入；
- remember_fn 失败时记录保持 pending（未确认的记忆不能凭空消失）。
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_memories (
    id           TEXT PRIMARY KEY,
    content      TEXT NOT NULL,
    category     TEXT NOT NULL DEFAULT 'general',
    memory_type  TEXT NOT NULL DEFAULT 'semantic',
    source_sentence TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'confirmed', 'rejected')),
    fingerprint  TEXT NOT NULL,
    memory_id    TEXT,
    proposed_by  TEXT NOT NULL DEFAULT '',
    created_at   REAL NOT NULL,
    decided_by   TEXT,
    decided_at   REAL,
    note         TEXT
);
CREATE INDEX IF NOT EXISTS pending_memories_status_idx
    ON pending_memories (status, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS pending_memories_rejected_fp_idx
    ON pending_memories (fingerprint) WHERE status = 'rejected';
"""


def _fingerprint(content: str) -> str:
    """内容指纹：去首尾空白 + 小写归一后哈希（拒绝名单判重用）。"""
    return hashlib.sha256(content.strip().lower().encode("utf-8")).hexdigest()


class PendingMemoryStore:
    """待确认记忆账本。独立分库，绝不与主记忆检索混表。"""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ── 提议 ──────────────────────────────────────────────────

    def propose(
        self,
        content: str,
        category: str = "general",
        memory_type: str = "semantic",
        source_sentence: str = "",
        proposed_by: str = "",
    ) -> Dict[str, Any]:
        """写入待审记录。命中已拒绝指纹 → 返回 rejected 标记（不新建）。"""
        content = (content or "").strip()
        if not content:
            raise ValueError("待确认记忆内容不能为空")
        fp = _fingerprint(content)
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM pending_memories WHERE fingerprint = ? AND status = 'rejected'",
                (fp,),
            ).fetchone()
            if row is not None:
                return {"rejected": True, "reason": "rejected_before", "id": row[0]}
            rec_id = str(uuid.uuid4())
            self._conn.execute(
                "INSERT INTO pending_memories"
                " (id, content, category, memory_type, source_sentence, status,"
                "  fingerprint, proposed_by, created_at)"
                " VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                (
                    rec_id,
                    content,
                    category or "general",
                    memory_type or "semantic",
                    source_sentence or "",
                    fp,
                    str(proposed_by or ""),
                    time.time(),
                ),
            )
            self._conn.commit()
            rec = self.get(rec_id)
            return rec if rec is not None else {"id": rec_id, "status": "pending"}

    # ── 查询 ──────────────────────────────────────────────────

    def get(self, pending_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, content, category, memory_type, source_sentence, status,"
                " memory_id, proposed_by, created_at, decided_by, decided_at, note"
                " FROM pending_memories WHERE id = ?",
                (pending_id,),
            ).fetchone()
        return self._to_dict(row) if row else None

    def list_pending(self, proposed_by: Optional[str] = None) -> List[Dict[str, Any]]:
        """待审清单（时间倒序）。proposed_by 给定时只看该用户的提议。"""
        with self._lock:
            if proposed_by:
                rows = self._conn.execute(
                    "SELECT id, content, category, memory_type, source_sentence, status,"
                    " memory_id, proposed_by, created_at, decided_by, decided_at, note"
                    " FROM pending_memories WHERE status = 'pending' AND proposed_by = ?"
                    " ORDER BY created_at DESC",
                    (str(proposed_by),),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id, content, category, memory_type, source_sentence, status,"
                    " memory_id, proposed_by, created_at, decided_by, decided_at, note"
                    " FROM pending_memories WHERE status = 'pending'"
                    " ORDER BY created_at DESC"
                ).fetchall()
        return [self._to_dict(r) for r in rows]

    def list_decisions(self, status: str = "confirmed") -> List[Dict[str, Any]]:
        """裁决历史（confirmed/rejected）。"""
        if status not in ("confirmed", "rejected"):
            raise ValueError("status 仅支持 confirmed/rejected")
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, content, category, memory_type, source_sentence, status,"
                " memory_id, proposed_by, created_at, decided_by, decided_at, note"
                " FROM pending_memories WHERE status = ? ORDER BY decided_at DESC",
                (status,),
            ).fetchall()
        return [self._to_dict(r) for r in rows]

    @staticmethod
    def _to_dict(row) -> Dict[str, Any]:
        return {
            "id": row[0],
            "content": row[1],
            "category": row[2],
            "memory_type": row[3],
            "source_sentence": row[4],
            "status": row[5],
            "memory_id": row[6],
            "proposed_by": row[7],
            "created_at": row[8],
            "decided_by": row[9],
            "decided_at": row[10],
            "note": row[11],
        }

    # ── 裁决 ──────────────────────────────────────────────────

    def confirm(self, pending_id: str, remember_fn: Callable[[str, str, str], str]) -> Dict[str, Any]:
        """确认入主库：remember_fn(content, category, memory_type) -> memory_id。
        remember_fn 失败时记录保持 pending（异常向上传播，由调用方提示）。"""
        with self._lock:
            rec = self.get(pending_id)
            if rec is None:
                raise LookupError("待确认记录不存在: %s" % pending_id)
            if rec["status"] != "pending":
                raise ValueError("该记录已裁决（%s），不能重复确认" % rec["status"])
            memory_id = remember_fn(rec["content"], rec["category"], rec["memory_type"])
            self._conn.execute(
                "UPDATE pending_memories SET status = 'confirmed', memory_id = ?,"
                " decided_at = ? WHERE id = ?",
                (str(memory_id), time.time(), pending_id),
            )
            self._conn.commit()
            out = self.get(pending_id)
            return out if out is not None else {"id": pending_id, "memory_id": str(memory_id)}

    def reject(self, pending_id: str, rejected_by: str = "", note: str = "") -> Dict[str, Any]:
        """拒绝提议并记指纹（同内容不再被重复提议）。"""
        with self._lock:
            rec = self.get(pending_id)
            if rec is None:
                raise LookupError("待确认记录不存在: %s" % pending_id)
            if rec["status"] != "pending":
                raise ValueError("该记录已裁决（%s）" % rec["status"])
            self._conn.execute(
                "UPDATE pending_memories SET status = 'rejected', decided_by = ?,"
                " decided_at = ?, note = ? WHERE id = ?",
                (str(rejected_by or ""), time.time(), note or None, pending_id),
            )
            self._conn.commit()
            out = self.get(pending_id)
            return out if out is not None else {"id": pending_id, "status": "rejected"}

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_process_store: Optional[PendingMemoryStore] = None
_process_lock = threading.Lock()


def get_pending_memory_store(db_path: str = "./data/memory_pending/pending_memories.db") -> PendingMemoryStore:
    """进程级单例（与 KnowledgeRepository.get_knowledge_repository 同式）。"""
    global _process_store
    with _process_lock:
        if _process_store is None:
            os.makedirs(str(Path(db_path).parent), exist_ok=True)
            _process_store = PendingMemoryStore(db_path=db_path)
        return _process_store
