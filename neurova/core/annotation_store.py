"""标注命中表（P2 — Dify Annotation Reply 对标）。

人工修正的问答固化为"精准回复"命中表：点赞 + 修正文本 → 沉淀，
后续相同/相近问题命中即返回精准回复（绕过模型重抽，黄铁定标的
工程化）。在记忆/知识体系之上最省事——独立 SQLite 表，不侵入既有
存储结构。

- 查询归一：小写 + 空白折叠 + 去尾部标点 → 精确命中；归一化子串兜底
  （长标注问命中短查询包含形态）
- hit_count：命中计数（标注价值度量，管理页排序依据）
- export_training_set：JSONL（input/output 对）——点赞对重训练化集
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def normalize_query(text: str) -> str:
    """查询归一：小写 + 空白折叠 + 去首尾标点/引号"""
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"^[\s\u3000。，,.!！?？;；:：'\"“”‘’、·]+|[\s\u3000。，,.!！?？;；:：'\"“”‘’、·]+$", "", t)
    return t


class AnnotationStore:
    """精准回复命中表（SQLite 持久化；线程安全）"""

    def __init__(self, db_path: str = "data/annotations.db"):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS annotations (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    question_norm TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    source TEXT DEFAULT 'manual',
                    enabled INTEGER DEFAULT 1,
                    hit_count INTEGER DEFAULT 0,
                    created_at REAL,
                    updated_at REAL
                )
            """)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_annotations_norm ON annotations(question_norm)"
            )
            self._conn.commit()

    def add(self, question: str, answer: str, source: str = "manual", enabled: bool = True) -> str:
        ann_id = str(uuid.uuid4())
        norm = normalize_query(question)
        with self._lock:
            self._conn.execute(
                "INSERT INTO annotations (id, question, question_norm, answer, source, enabled, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, strftime('%s','now'), strftime('%s','now'))",
                (ann_id, question, norm, answer, source, 1 if enabled else 0),
            )
            self._conn.commit()
        return ann_id

    def get(self, ann_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM annotations WHERE id = ?", (ann_id,)).fetchone()
        return dict(row) if row else None

    def update_answer(self, ann_id: str, answer: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE annotations SET answer = ?, updated_at = strftime('%s','now') WHERE id = ?",
                (answer, ann_id),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def set_enabled(self, ann_id: str, enabled: bool) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE annotations SET enabled = ?, updated_at = strftime('%s','now') WHERE id = ?",
                (1 if enabled else 0, ann_id),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def delete(self, ann_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM annotations WHERE id = ?", (ann_id,))
            self._conn.commit()
        return cur.rowcount > 0

    def list_annotations(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM annotations ORDER BY hit_count DESC, updated_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS c FROM annotations").fetchone()
        return int(row["c"]) if row else 0

    def _bump_hit(self, ann_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE annotations SET hit_count = hit_count + 1 WHERE id = ?", (ann_id,)
            )
            self._conn.commit()

    def export_training_set(self) -> List[str]:
        """重训练化集：启用的标注 → JSONL 行（{"input", "output"}）"""
        out: List[str] = []
        for row in self.list_annotations(limit=100000):
            if not row.get("enabled"):
                continue
            out.append(json.dumps(
                {"input": row["question"], "output": row["answer"]},
                ensure_ascii=False,
            ))
        return out

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def match_annotation(store: AnnotationStore, user_input: str) -> Optional[Dict[str, Any]]:
    """命中面：归一精确 → 归一子串兜底；命中即返回标注行（并计 hit_count）"""
    norm = normalize_query(user_input)
    if not norm:
        return None
    with store._lock:
        row = store._conn.execute(
            "SELECT * FROM annotations WHERE enabled = 1 AND question_norm = ? ORDER BY hit_count DESC LIMIT 1",
            (norm,),
        ).fetchone()
        if row is None:
            # 子串兜底：归一查询是某标注问题的包含形态（前缀式提问）
            row = store._conn.execute(
                "SELECT * FROM annotations WHERE enabled = 1 AND instr(?, question_norm) > 0"
                " ORDER BY LENGTH(question_norm) DESC LIMIT 1",
                (norm,),
            ).fetchone()
        if row is None:
            return None
        ann = dict(row)
    store._bump_hit(ann["id"])
    return ann


__all__ = ["AnnotationStore", "match_annotation", "normalize_query"]


# 单例（进程级；chat 反馈链路与 annotation API 共用）
_annotation_store: Optional[AnnotationStore] = None
_annotation_store_lock = threading.Lock()


def get_annotation_store() -> AnnotationStore:
    """获取标注命中表单例（缺省 data/annotations.db）"""
    global _annotation_store
    if _annotation_store is None:
        with _annotation_store_lock:
            if _annotation_store is None:
                _annotation_store = AnnotationStore()
    return _annotation_store


def set_annotation_store(store: Optional[AnnotationStore]) -> None:
    """注入/重置单例（测试隔离用）"""
    global _annotation_store
    _annotation_store = store
