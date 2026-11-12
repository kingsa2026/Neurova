"""状态机登记面（specs/2026-11-12 §5 W3）：ontology_state_machines 唯一读写面。

- 状态机是**数据**（通则 2）：states/transitions/event_bindings 全部 JSON 闭集，
  登记即校验——transitions 的 from/to 必须落在 states 内、initial_state 必须在
  states 内，越界登记即拒。
- 迁移约束的求值单点在 validation（主体 term 有状态机时，新 has_state 值的
  from→to 须在 transitions 内）；本模块只管登记与读数，不复制第二份判据。
- v44 DDL：本表＋enterprise_source_configs 的 sync_interval_seconds 列
  （interval 同步间隔，企业源注册面消费）。
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Dict, List, Optional

SCHEMA_V44_STATE_MACHINES = "_SCHEMA_V44_STATE_MACHINES"

_SCHEMA_V44_STATE_MACHINES = """
CREATE TABLE IF NOT EXISTS ontology_state_machines (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    term_id TEXT NOT NULL,
    states_json TEXT NOT NULL DEFAULT '[]',
    transitions_json TEXT NOT NULL DEFAULT '[]',
    initial_state TEXT NOT NULL DEFAULT '',
    event_bindings_json TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, term_id)
);
ALTER TABLE enterprise_source_configs ADD COLUMN sync_interval_seconds
    INTEGER NOT NULL DEFAULT 0;
"""

_HAS_STATE_PREDICATE = "has_state"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class StateMachineRegistry:
    """ontology_state_machines 的唯一读写面。"""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._ensureTable()

    def _ensureTable(self) -> None:
        from ..foundation.foundation_schema import applyTo

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    # ── 写 ────────────────────────────────────────────────────

    def register(self, termId: str, tenantId: str = "default",
                 states: Optional[List[str]] = None,
                 transitions: Optional[List[Dict[str, Any]]] = None,
                 initialState: str = "",
                 eventBindings: Optional[List[Dict[str, Any]]] = None,
                 enabled: bool = True) -> Dict[str, Any]:
        """登记（INSERT OR REPLACE）。states 是闭集：transitions 的 from/to 与
        initial_state 越界登记即拒。term_id 须是注册表在册 concept（状态机挂在
        主体类型上）。"""
        termId = str(termId or "").strip()
        states = [str(s or "").strip() for s in (states or []) if str(s or "").strip()]
        transitions = [dict(t) for t in (transitions or [])]
        if not termId:
            raise ValueError("term_id 缺失")
        if not states:
            raise ValueError("states 闭集缺失")
        closed = set(states)
        if str(initialState or "").strip() not in closed:
            raise ValueError("initial_state %r 不在 states 闭集" % initialState)
        for t in transitions:
            for side in ("from", "to"):
                if str(t.get(side) or "").strip() not in closed:
                    raise ValueError(
                        "transitions 的 %s=%r 不在 states 闭集 %r" % (side, t.get(side), states))
        for b in (eventBindings or []):
            for field in ("eventName", "subjectField", "stateField"):
                if not str(b.get(field) or "").strip():
                    raise ValueError("event_bindings 缺 %s" % field)
        from ..foundation.knowledge_facts import get_knowledge_fact_store

        store = self._store if self._store is not None else get_knowledge_fact_store()
        from .term_registry import OntologyTermRegistry

        term = OntologyTermRegistry(store).term(termId, tenantId=tenantId)
        if term is None or str(term.get("kind")) != "concept":
            raise ValueError("term_id %r 须是注册表在册 concept（状态机挂主体类型）" % termId)
        with self._store._lock, self._store._conn:
            existing = self._store._conn.execute(
                "SELECT created_at FROM ontology_state_machines"
                " WHERE tenant_id = ? AND term_id = ?",
                (str(tenantId or "default"), termId)).fetchone()
            self._store._conn.execute(
                "INSERT OR REPLACE INTO ontology_state_machines"
                " (tenant_id, term_id, states_json, transitions_json, initial_state,"
                "  event_bindings_json, enabled, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (str(tenantId or "default"), termId,
                 json.dumps(states, ensure_ascii=False),
                 json.dumps(transitions, ensure_ascii=False),
                 str(initialState or "").strip(),
                 json.dumps(list(eventBindings or []), ensure_ascii=False),
                 1 if enabled else 0,
                 existing["created_at"] if existing else _now(), _now()))
        return self.get(termId, tenantId=tenantId) or {}

    def update(self, termId: str, tenantId: str = "default", **fields: Any) -> Dict[str, Any]:
        existing = self.get(termId, tenantId=tenantId)
        if existing is None:
            raise LookupError("状态机未登记: %s" % termId)
        merged = dict(existing)
        for key, param in (("states", "states"), ("transitions", "transitions"),
                           ("initial_state", "initialState"),
                           ("event_bindings", "eventBindings"), ("enabled", "enabled")):
            if param in fields:
                merged[key] = fields[param]
        return self.register(
            termId=termId, tenantId=tenantId, states=merged.get("states"),
            transitions=merged.get("transitions"),
            initialState=str(merged.get("initial_state") or ""),
            eventBindings=merged.get("event_bindings"),
            enabled=bool(merged.get("enabled")))

    def delete(self, termId: str, tenantId: str = "default") -> bool:
        with self._store._lock, self._store._conn:
            cursor = self._store._conn.execute(
                "DELETE FROM ontology_state_machines WHERE tenant_id = ? AND term_id = ?",
                (str(tenantId or "default"), str(termId or "").strip()))
            return cursor.rowcount > 0

    # ── 读 ────────────────────────────────────────────────────

    def get(self, termId: str, tenantId: str = "default") -> Optional[Dict[str, Any]]:
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT * FROM ontology_state_machines WHERE tenant_id = ? AND term_id = ?",
                (str(tenantId or "default"), str(termId or "").strip())).fetchone()
        return self._hydrate(row) if row is not None else None

    def list(self, tenantId: str = "default",
             includeDisabled: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM ontology_state_machines WHERE tenant_id = ?"
        if not includeDisabled:
            sql += " AND enabled = 1"
        sql += " ORDER BY term_id"
        with self._store._lock:
            rows = self._store._conn.execute(sql, (str(tenantId or "default"),)).fetchall()
        return [self._hydrate(row) for row in rows]

    def eventBindings(self, tenantId: str = "default") -> List[Dict[str, Any]]:
        """全部启用机的 event_bindings 平铺（事件桥启动清单）。"""
        out: List[Dict[str, Any]] = []
        for machine in self.list(tenantId=tenantId):
            for binding in machine.get("event_bindings") or []:
                out.append(dict(binding, term_id=machine["term_id"]))
        return out

    def currentState(self, agentId: str, subjectKey: str,
                     tenantId: str = "default") -> str:
        """主体当前 active has_state 值（cardinality=1 ⇒ 至多一条；空＝无当前状态）。"""
        facts = self._store.factsForSubject(subjectKey)
        for fact in facts:
            if str(fact.get("predicate_term_id")) == _HAS_STATE_PREDICATE \
                    and str(fact.get("status")) == "active" \
                    and str(fact.get("agent_id")) == str(agentId):
                return str(fact.get("object_term") or "")
        return ""

    @staticmethod
    def _hydrate(row: Any) -> Dict[str, Any]:
        d = dict(row)
        d["states"] = json.loads(d.pop("states_json") or "[]")
        d["transitions"] = json.loads(d.pop("transitions_json") or "[]")
        d["event_bindings"] = json.loads(d.pop("event_bindings_json") or "[]")
        d["enabled"] = bool(d.get("enabled"))
        return d
