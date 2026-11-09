# -*- coding: utf-8 -*-
"""本体动作注册表（Ontology 接入 Agent 补全设计 A4，第 3 步"动作与权限建模"
的最小运行时面）。

动作 = **声明**：绑定一个既有工具（bound_tool）与参数模板，风险档由登记者
声明——它是治理侧的元数据读数（治理中心按 risk_tier 过滤展示、按动作名配
白名单/审批），Agent 侧经 ontology_query(kind='action') 可查动作清单与风险档
（决策时知道哪些动作要审批）。**不改判定逻辑**：resolveCommandAuthority/
evaluate_tool_call 的判定链不动；动作运行时执行仍走既有 tool_call 单工具边界。

刻意不做：动作编排/回滚/事务（NeurFlow 领地）；按动作的独立执行引擎
（与 tool_call 并行即平行体系）。
"""

from __future__ import annotations

import datetime
import json
import threading
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 风险档闭集——治理侧按档过滤展示/审批的元数据读数。
RISK_TIERS = ("low", "medium", "high")

_SCHEMA_V42_ACTIONS = """
CREATE TABLE IF NOT EXISTS ontology_actions (
    action_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    definition TEXT NOT NULL DEFAULT '',
    param_schema_json TEXT NOT NULL DEFAULT '{}',
    bound_tool TEXT NOT NULL DEFAULT '',
    risk_tier TEXT NOT NULL DEFAULT 'low',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, action_id)
);
"""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class ActionRegistry:
    """`ontology_actions` 的唯一读写面（租户分区，与本体术语同款隔离语义）。"""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._ensureTable()

    def _ensureTable(self) -> None:
        from ..foundation.foundation_schema import applyTo

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    def upsert(self, actionId: str, *, label: str, definition: str = "",
               paramSchema: Optional[Dict[str, Any]] = None, boundTool: str,
               riskTier: str = "low", enabled: bool = True,
               tenantId: str = "default",
               registeredTools: Optional[List[str]] = None) -> Dict[str, Any]:
        """登记/更新动作。bound_tool 悬空拒（动作必须落在真实工具上）；
        risk_tier 闭集校验；paramSchema 必须是 JSON 对象。"""
        actionId = str(actionId or "").strip()
        if not actionId:
            raise ValueError("action_id 不能为空")
        riskTier = str(riskTier or "").strip()
        if riskTier not in RISK_TIERS:
            raise ValueError(
                "未知风险档 %r（有效值: %s）" % (riskTier, "/".join(RISK_TIERS)))
        boundTool = str(boundTool or "").strip()
        if not boundTool:
            raise ValueError("bound_tool 不能为空（动作必须绑定既有工具）")
        if registeredTools is not None and boundTool not in registeredTools:
            raise ValueError(
                "bound_tool %r 未在工具注册表登记（悬空动作拒绝）" % boundTool)
        if not isinstance(paramSchema or {}, dict):
            raise ValueError("param_schema 必须是 JSON 对象")
        stamp = _now()
        with self._store._lock, self._store._conn:
            existing = self._store._conn.execute(
                "SELECT created_at FROM ontology_actions"
                " WHERE tenant_id = ? AND action_id = ?", (tenantId, actionId)
            ).fetchone()
            self._store._conn.execute(
                "INSERT OR REPLACE INTO ontology_actions"
                " (tenant_id, action_id, label, definition, param_schema_json,"
                "  bound_tool, risk_tier, enabled, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (tenantId, actionId, label or actionId, definition or "",
                 json.dumps(paramSchema or {}, ensure_ascii=False), boundTool,
                 riskTier, 1 if enabled else 0,
                 existing["created_at"] if existing else stamp, stamp))
        return self.action(actionId, tenantId=tenantId) or {}

    def action(self, actionId: str, tenantId: str = "default") -> Optional[Dict[str, Any]]:
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT * FROM ontology_actions WHERE tenant_id = ? AND action_id = ?",
                (str(tenantId or "default"), str(actionId))).fetchone()
        if row is None:
            return None
        return self._hydrate(row)

    def list(self, tenantId: str = "default",
             riskTier: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM ontology_actions WHERE tenant_id = ?"
        params: List[Any] = [str(tenantId or "default")]
        if riskTier:
            sql += " AND risk_tier = ?"
            params.append(riskTier)
        with self._store._lock:
            rows = self._store._conn.execute(sql + " ORDER BY action_id",
                                             params).fetchall()
        return [self._hydrate(r) for r in rows]

    def drop(self, actionId: str, tenantId: str = "default") -> bool:
        with self._store._lock, self._store._conn:
            cur = self._store._conn.execute(
                "DELETE FROM ontology_actions WHERE tenant_id = ? AND action_id = ?",
                (str(tenantId or "default"), str(actionId)))
        return cur.rowcount > 0

    def _hydrate(self, row: Any) -> Dict[str, Any]:
        d = dict(row)
        d["param_schema"] = json.loads(d.pop("param_schema_json") or "{}")
        d["enabled"] = bool(d.get("enabled"))
        return d


def getActionRegistry(store: Any) -> ActionRegistry:
    return ActionRegistry(store)
