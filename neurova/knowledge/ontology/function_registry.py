"""函数层登记面（specs/2026-11-12 §4 W2）：ontology_functions 唯一读写面。

- 表 DDL 常量 `_SCHEMA_V43_FUNCTIONS` 由此处持有（v43 迁移经 foundation_schema
  注册表装配，领域模块自持 DDL——v42 动作表同款先例）。
- 登记即编译校验：表达式（function_eval 白名单）＋output_predicate 须在术语
  注册表（B-10 纪律）；超深度超尺寸/未知符号/越界节点一律拒。
- ActionRegistry 同款租户隔离（PK tenant_id+function_id）。
- 删除＝精确撤销：`derivation_ledger.retractAllFromRule("function:<id>")`
  只撤该函数的结论（rule_id 位写 function:<id>，账本单源不建第二张）。
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Dict, List, Optional

_SCHEMA_V43_FUNCTIONS = """
CREATE TABLE IF NOT EXISTS ontology_functions (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    function_id TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    definition TEXT NOT NULL DEFAULT '',
    expr_text TEXT NOT NULL DEFAULT '',
    input_bindings_json TEXT NOT NULL DEFAULT '{}',
    output_predicate TEXT NOT NULL DEFAULT '',
    scope_json TEXT NOT NULL DEFAULT '{}',
    materialization TEXT NOT NULL DEFAULT 'observe',
    enabled INTEGER NOT NULL DEFAULT 1,
    version TEXT NOT NULL DEFAULT 'v1',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, function_id)
);
ALTER TABLE knowledge_derivation_edges ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'rule';
"""

_MATERIALIZATIONS = ("observe", "enforce")

_NOW_COL = "datetime"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class FunctionRegistry:
    """ontology_functions 的唯一读写面（ActionRegistry 同款形状）。"""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._ensureTable()

    def _ensureTable(self) -> None:
        from ..foundation.foundation_schema import applyTo

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    # ── 写 ────────────────────────────────────────────────────

    def register(self, functionId: str, tenantId: str = "default",
                 exprText: str = "", outputPredicate: str = "",
                 inputBindings: Optional[Dict[str, Any]] = None,
                 scope: Optional[Dict[str, Any]] = None,
                 materialization: str = "observe", label: str = "",
                 definition: str = "", enabled: bool = True,
                 version: str = "v1") -> Dict[str, Any]:
        """登记（INSERT OR REPLACE）。登记即编译；编译产物的选择器依赖写进
        scope_json['depends_on']（fireFor 过滤读它，不再扫表达式）。"""
        functionId = str(functionId or "").strip()
        outputPredicate = str(outputPredicate or "").strip()
        if not functionId:
            raise ValueError("function_id 缺失")
        if materialization not in _MATERIALIZATIONS:
            raise ValueError("物化档 %r 不在闭集 %r" % (materialization, _MATERIALIZATIONS))
        from ..foundation.knowledge_facts import get_knowledge_fact_store

        store = self._store if self._store is not None else get_knowledge_fact_store()
        from .term_registry import OntologyTermRegistry

        registry = OntologyTermRegistry(store)
        term = registry.term(outputPredicate, tenantId=tenantId)
        if term is None or str(term.get("kind")) != "relation":
            raise ValueError("output_predicate %r 须是注册表在册关系（B-10）" % outputPredicate)
        allowedPredicates = tuple(str(t.get("term_id") or "")
                                  for t in registry.terms(kind="relation", tenantId=tenantId))
        bindings = dict(inputBindings or {})
        from .function_eval import compileFunction

        compiled = compileFunction(exprText, allowedNames=tuple(bindings.keys()),
                                   allowedPredicates=allowedPredicates)
        scopeFull = dict(scope or {})
        scopeFull["depends_on"] = sorted(set(compiled.selectorPredicates))
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "INSERT OR REPLACE INTO ontology_functions"
                " (tenant_id, function_id, label, definition, expr_text,"
                "  input_bindings_json, output_predicate, scope_json,"
                "  materialization, enabled, version, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(tenantId or "default"), functionId, str(label or ""),
                 str(definition or ""), compiled.exprText,
                 json.dumps(bindings, ensure_ascii=False), outputPredicate,
                 json.dumps(scopeFull, ensure_ascii=False),
                 materialization, 1 if enabled else 0, str(version or "v1"),
                 _now(), _now()))
        return self.get(functionId, tenantId=tenantId) or {}

    def update(self, functionId: str, tenantId: str = "default", **fields: Any) -> Dict[str, Any]:
        """部分更新：expr/output/bindings 改动会重过编译；其余直改。"""
        existing = self.get(functionId, tenantId=tenantId)
        if existing is None:
            raise LookupError("函数未登记: %s（租户 %s）" % (functionId, tenantId))
        merged = dict(existing)
        merged.update({k: v for k, v in fields.items() if k in (
            "label", "definition", "expr_text", "input_bindings",
            "output_predicate", "scope", "materialization", "enabled", "version")})
        return self.register(
            functionId=functionId, tenantId=tenantId,
            exprText=str(merged.get("expr_text") or ""),
            outputPredicate=str(merged.get("output_predicate") or ""),
            inputBindings=merged.get("input_bindings") or {},
            scope=merged.get("scope") or {},
            materialization=str(merged.get("materialization") or "observe"),
            label=str(merged.get("label") or ""),
            definition=str(merged.get("definition") or ""),
            enabled=bool(merged.get("enabled")),
            version=str(merged.get("version") or "v1"))

    def delete(self, functionId: str, tenantId: str = "default",
               reason: str = "") -> int:
        """删函数并撤回它推过的全部结论——函数没了，它的推导不能还在对外检索
        （rule_engine.dropRule 同款按源撤销，账本单源）。"""
        functionId = str(functionId or "").strip()
        tenant = str(tenantId or "default")
        if self.get(functionId, tenantId=tenant) is None:
            raise LookupError("函数未登记: %s" % functionId)
        self._store._derivationLedger.retractAllFromRule(
            "function:%s" % functionId,
            reason or "函数 %s 已删除" % functionId, tenantId=tenant)
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "DELETE FROM ontology_functions WHERE tenant_id = ? AND function_id = ?",
                (tenant, functionId))
        return 1

    # ── 读 ────────────────────────────────────────────────────

    def get(self, functionId: str, tenantId: str = "default") -> Optional[Dict[str, Any]]:
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT * FROM ontology_functions WHERE tenant_id = ? AND function_id = ?",
                (str(tenantId or "default"), str(functionId or "").strip())).fetchone()
        return self._hydrate(row) if row is not None else None

    def list(self, tenantId: str = "default",
             includeDisabled: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM ontology_functions WHERE tenant_id = ?"
        if not includeDisabled:
            sql += " AND enabled = 1"
        sql += " ORDER BY function_id"
        with self._store._lock:
            rows = self._store._conn.execute(sql, (str(tenantId or "default"),)).fetchall()
        return [self._hydrate(row) for row in rows]

    @staticmethod
    def _hydrate(row: Any) -> Dict[str, Any]:
        d = dict(row)
        d["input_bindings"] = json.loads(d.pop("input_bindings_json") or "{}")
        d["scope"] = json.loads(d.pop("scope_json") or "{}")
        d["enabled"] = bool(d.get("enabled"))
        return d
