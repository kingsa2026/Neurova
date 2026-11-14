"""本体变更审计账（B12 L8，升级计划 §12.9）：只追加，不删除。

本体写面（terms/rules/shapes/pipeline/rollback）的每一笔变更落一行
before/after 快照——"谁在什么时候把什么改成了什么"必须可对账。
账本不提供 delete/purge：审计账能删就不是审计账。
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List
from neurova.core.time_utils import nowIso as _now

_SCHEMA_V33 = """
CREATE TABLE IF NOT EXISTS ontology_change_log (
    change_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL DEFAULT '',
    before_json TEXT NOT NULL DEFAULT '{}',
    after_json TEXT NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL DEFAULT '',
    baseline_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_change_log_review
    ON ontology_change_log(tenant_id, created_at);
"""


class ChangeLog:
    """`ontology_change_log` 的唯一读写面（append/list 两个动词，刻意不多）。"""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._ensureTable()

    def _ensureTable(self) -> None:
        from ..foundation.foundation_schema import applyTo

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    def append(self, tenantId: str, actor: str, action: str, targetType: str,
               targetId: str = "", beforeJson: Any = None, afterJson: Any = None,
               reason: str = "", baselineId: str = "") -> str:
        changeId = "chg_%s" % uuid.uuid4().hex[:12]
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "INSERT INTO ontology_change_log (change_id, tenant_id, actor, action,"
                " target_type, target_id, before_json, after_json, reason, baseline_id,"
                " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (changeId, str(tenantId or "default"), str(actor or ""), str(action or ""),
                 str(targetType or ""), str(targetId or ""),
                 str(beforeJson or "{}") if isinstance(beforeJson, str)
                 else __import__("json").dumps(beforeJson or {}, ensure_ascii=False,
                                               sort_keys=True),
                 str(afterJson or "{}") if isinstance(afterJson, str)
                 else __import__("json").dumps(afterJson or {}, ensure_ascii=False,
                                               sort_keys=True),
                 str(reason or ""), str(baselineId or ""), _now()),
            )
        return changeId

    def list(self, tenantId: str = "default", limit: int = 200) -> List[Dict[str, Any]]:
        with self._store._lock:
            rows = self._store._conn.execute(
                "SELECT * FROM ontology_change_log WHERE tenant_id = ?"
                " ORDER BY created_at, change_id LIMIT ?",
                (str(tenantId or "default"), int(limit))).fetchall()
        return [dict(r) for r in rows]
