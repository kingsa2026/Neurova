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
    note         TEXT,
    proposed_action TEXT NOT NULL DEFAULT 'store',
    target_memory_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS pending_memories_status_idx
    ON pending_memories (status, created_at DESC);
"""

# 2026-09-07 事故修复（/agent/default/memory 拒绝入库报
# UNIQUE constraint failed: pending_memories.fingerprint）：
# 旧索引只约束 rejected 单墓碑，propose 却允许同指纹 pending 无限堆积——
# 堆积后第二次拒绝必然撞索引。不变量收紧为"每指纹×每提议人至多一条未决行"：
# propose 对未决指纹幂等回指、reject 单向改判，索引冲突从状态机上不可达。
# 2026-09-07 用户拍板：判重按提议人隔离（跨用户不互相封存），
# 未决槽位键改为 (fingerprint, proposed_by)，匿名桶（''）自成一域。
# 两个历史索引定义都废弃：单墓碑版（rejected_fp_idx）与全局指纹版
# （live_fp_idx 旧定义），同名的隔离版索引在清洗后重建。
_MIGRATION_DROP_OLD = (
    "DROP INDEX IF EXISTS pending_memories_rejected_fp_idx;"
    "DROP INDEX IF EXISTS pending_memories_live_fp_idx;"
)

# 存量堆积收敛（幂等）：有墓碑的 (指纹, 提议人) 分区下残留 pending 由墓碑
# 代表裁决，直接清除；无墓碑的同分区 pending 堆积保留最新一条
# （内容归一化相同，无信息损失）。
_LEGACY_CLEANUP = """
DELETE FROM pending_memories
 WHERE status = 'pending'
   AND EXISTS (
       SELECT 1 FROM pending_memories r
        WHERE r.status = 'rejected'
          AND r.fingerprint = pending_memories.fingerprint
          AND r.proposed_by = pending_memories.proposed_by
   );
DELETE FROM pending_memories
 WHERE status = 'pending'
   AND id NOT IN (
       SELECT id FROM (
           SELECT id, ROW_NUMBER() OVER (
               PARTITION BY fingerprint, proposed_by ORDER BY created_at DESC, rowid DESC
           ) AS rn
             FROM pending_memories
            WHERE status = 'pending'
       )
       WHERE rn = 1
   );
-- P2-5（审计 2026-09-11）：唯一索引谓词含 rejected，存量同分区多条
-- rejected 会让 CREATE UNIQUE INDEX 抛错 → 建库失败每次启动复现。
-- 建索引前对 rejected 同分区去重（保留最新 decided_at）。
DELETE FROM pending_memories
 WHERE status = 'rejected'
   AND id NOT IN (
       SELECT id FROM (
           SELECT id, ROW_NUMBER() OVER (
               PARTITION BY fingerprint, proposed_by ORDER BY decided_at DESC, rowid DESC
           ) AS rn
             FROM pending_memories
            WHERE status = 'rejected'
       )
       WHERE rn = 1
   );
"""

_LIVE_FP_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS pending_memories_live_fp_idx
    ON pending_memories (fingerprint, proposed_by)
    WHERE status IN ('pending', 'rejected');
"""

# 核验轮修复②：存量库幂等列迁移（CREATE TABLE 只覆盖新建库）。旧库缺
# proposed_action/target_memory_id 两列时补齐，默认值保持旧行为语义
# （store、无目标）。
def _migrate_action_columns(conn: "sqlite3.Connection") -> None:
    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(pending_memories)").fetchall()
    }
    if "proposed_action" not in existing:
        conn.execute(
            "ALTER TABLE pending_memories ADD COLUMN proposed_action TEXT NOT NULL DEFAULT 'store'"
        )
    if "target_memory_id" not in existing:
        conn.execute(
            "ALTER TABLE pending_memories ADD COLUMN target_memory_id TEXT NOT NULL DEFAULT ''"
        )


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
        self._conn.executescript(_MIGRATION_DROP_OLD)
        self._migrate_columns()
        self._conn.executescript(_LEGACY_CLEANUP)
        self._conn.executescript(_LIVE_FP_INDEX)
        self._conn.commit()

    def _migrate_columns(self) -> None:
        try:
            _migrate_action_columns(self._conn)
            self._conn.commit()
        except Exception:  # noqa: BLE001 - 迁移失败不阻断建库，待下次启动重试
            self._conn.rollback()

    # ── 提议 ──────────────────────────────────────────────────

    def propose(
        self,
        content: str,
        category: str = "general",
        memory_type: str = "semantic",
        source_sentence: str = "",
        proposed_by: str = "",
        proposed_action: str = "store",
        target_memory_id: str = "",
    ) -> Dict[str, Any]:
        """写入待审记录。命中未决指纹幂等回指（rejected 墓碑 → 拒绝标记，
        pending → 回指既有记录），不新建。判重按提议人隔离：
        (指纹, proposed_by) 分区内至多一条未决行，跨用户互不封存。

        核验轮修复②（forget 审批闭环）：proposed_action 标记动作类型
        （store 新增 / forget 遗忘），confirm 端点据此分流执行——此前
        forget 提议与普通新增无差别，确认会把遗忘摘要当新记忆入主库。"""
        content = (content or "").strip()
        if not content:
            raise ValueError("待确认记忆内容不能为空")
        action = str(proposed_action or "store").strip().lower()
        if action not in ("store", "forget"):
            raise ValueError(f"未知 proposed_action: {action}")
        target = str(target_memory_id or "").strip()
        if action == "forget" and not target:
            raise ValueError("forget 提议缺少 target_memory_id")
        fp = _fingerprint(content)
        # 审计⑤：forget 提议的判重指纹只绑定目标记忆——content 是模型自填
        # 摘要（展示用），旧口径哈希 content 导致：不同 target 的同摘要提议
        # 撞车（confirm 删错记忆）、同 target 换摘要绕过拒绝墓碑、与同内容
        # store 提议互相顶替（确认语义反转：删变存）。
        if action == "forget":
            fp = _fingerprint(f"forget\x00{target}")
        owner = str(proposed_by or "")
        with self._lock:
            row = self._conn.execute(
                "SELECT id, status FROM pending_memories"
                " WHERE fingerprint = ? AND proposed_by = ?"
                " AND status IN ('pending', 'rejected')",
                (fp, owner),
            ).fetchone()
            if row is not None:
                if row[1] == "rejected":
                    return {"rejected": True, "reason": "rejected_before", "id": row[0]}
                rec = self.get(row[0])
                assert rec is not None  # 同事务刚查出，库内自洽
                return rec
            rec_id = str(uuid.uuid4())
            self._conn.execute(
                "INSERT INTO pending_memories"
                " (id, content, category, memory_type, source_sentence, status,"
                "  fingerprint, proposed_by, created_at, proposed_action, target_memory_id)"
                " VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)",
                (
                    rec_id,
                    content,
                    category or "general",
                    memory_type or "semantic",
                    source_sentence or "",
                    fp,
                    str(proposed_by or ""),
                    time.time(),
                    action,
                    target,
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
                " memory_id, proposed_by, created_at, decided_by, decided_at, note, proposed_action, target_memory_id"
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
                    " memory_id, proposed_by, created_at, decided_by, decided_at, note, proposed_action, target_memory_id"
                    " FROM pending_memories WHERE status = 'pending' AND proposed_by = ?"
                    " ORDER BY created_at DESC, rowid DESC",
                    (str(proposed_by),),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id, content, category, memory_type, source_sentence, status,"
                    " memory_id, proposed_by, created_at, decided_by, decided_at, note, proposed_action, target_memory_id"
                    " FROM pending_memories WHERE status = 'pending'"
                    " ORDER BY created_at DESC, rowid DESC"
                ).fetchall()
        return [self._to_dict(r) for r in rows]

    def list_decisions(self, status: str = "confirmed") -> List[Dict[str, Any]]:
        """裁决历史（confirmed/rejected）。"""
        if status not in ("confirmed", "rejected"):
            raise ValueError("status 仅支持 confirmed/rejected")
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, content, category, memory_type, source_sentence, status,"
                " memory_id, proposed_by, created_at, decided_by, decided_at, note, proposed_action, target_memory_id"
                " FROM pending_memories WHERE status = ? ORDER BY decided_at DESC, rowid DESC",
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
            "proposed_action": row[12],
            "target_memory_id": row[13],
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
