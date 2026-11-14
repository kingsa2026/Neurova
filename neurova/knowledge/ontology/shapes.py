"""本体形状注册表（B10 L4，升级计划 §12.5）：SHACL 语义的完整性约束面。

与既有 6 项固定校验的关系（先比后合，教义第 7 条）：6 项收编为**内置 shape**，
求值只有一份——`evaluateForRequest` 把用户 shape 的判定结果追加进同一 findings 流；
用户 shape 与内置 shape 撞车（constraintKind 落在内置闭集）登记即拒，不复制第二套。

严重级三态：violation（violations() 收，写前阻断）/ warning（记账）/ info（遥测）。
形状 DSL 是 JSON 子集（in/pattern/minCount/maxCount/class），不引第三方 SHACL 引擎；
形状只判数据不触发推导，rule 只推导不做完整性校验（推理与校验分离）。
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional
from neurova.core.time_utils import nowIso as _now

#: 内置 constraintKind 闭集：这些维度由 validation.py 的固定校验拥有，
#: 用户 shape 声明同名维度即撞车（单一事实源，教义第 6 条）。
BUILTIN_CONSTRAINT_KINDS = (
    "domain", "range", "parentConsistency", "disjoint", "cardinality", "requiredProps",
)

_SEVERITIES = ("violation", "warning", "info")

#: JSON DSL 支持的 constraintKind 闭集（B12 导出 SHACL shapes 时逐项映射）。
DSL_CONSTRAINT_KINDS = ("in", "pattern", "minCount", "maxCount", "class")

_SCHEMA_V31_SHAPES = """
CREATE TABLE IF NOT EXISTS ontology_shapes (
    shape_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target_term_id TEXT NOT NULL DEFAULT '',
    path_json TEXT NOT NULL DEFAULT '{}',
    constraint_kind TEXT NOT NULL,
    constraint_json TEXT NOT NULL DEFAULT '{}',
    severity TEXT NOT NULL DEFAULT 'violation',
    message TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT 1,
    version TEXT NOT NULL DEFAULT 'v1',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, shape_id)
);
CREATE INDEX IF NOT EXISTS idx_shapes_target
    ON ontology_shapes(tenant_id, target_term_id, enabled);
"""


class ShapeRegistry:
    """`ontology_shapes` 的唯一读写面与求值入口。"""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._ensureTable()

    def _ensureTable(self) -> None:
        from ..foundation.foundation_schema import applyTo

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    def register(self, tenantId: str, shapeId: str, targetKind: str,
                 constraintKind: str, constraintJson: Dict[str, Any],
                 pathJson: Optional[Dict[str, Any]] = None,
                 targetTermId: str = "", severity: str = "violation",
                 message: str = "", enabled: bool = True,
                 version: str = "v1") -> Dict[str, Any]:
        tenant = str(tenantId or "default")
        shapeId = str(shapeId or "").strip()
        constraintKind = str(constraintKind or "").strip()
        severity = str(severity or "violation")
        if not shapeId:
            raise ValueError("shape_id 不能为空")
        if targetKind not in ("relation", "concept"):
            raise ValueError("未知 target_kind %r（有效值: relation / concept）" % targetKind)
        if constraintKind in BUILTIN_CONSTRAINT_KINDS:
            raise ValueError(
                "shape %s 的 constraintKind %r 与内置校验撞车（单一事实源，教义第 6 条）；"
                "内置维度：%s" % (shapeId, constraintKind, " / ".join(BUILTIN_CONSTRAINT_KINDS)))
        if constraintKind not in DSL_CONSTRAINT_KINDS:
            raise ValueError(
                "未知 constraintKind %r（DSL 闭集: %s）"
                % (constraintKind, " / ".join(DSL_CONSTRAINT_KINDS)))
        if severity not in _SEVERITIES:
            raise ValueError("未知 severity %r（有效值: %s）" % (severity, " / ".join(_SEVERITIES)))
        stamp = _now()
        with self._store._lock, self._store._conn:
            existing = self._store._conn.execute(
                "SELECT created_at FROM ontology_shapes"
                " WHERE tenant_id = ? AND shape_id = ?", (tenant, shapeId)).fetchone()
            self._store._conn.execute(
                "INSERT OR REPLACE INTO ontology_shapes (tenant_id, shape_id, target_kind,"
                " target_term_id, path_json, constraint_kind, constraint_json, severity,"
                " message, enabled, version, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tenant, shapeId, str(targetKind), str(targetTermId or ""),
                 json.dumps(pathJson or {}, ensure_ascii=False), constraintKind,
                 json.dumps(constraintJson or {}, ensure_ascii=False), severity,
                 str(message or ""), 1 if enabled else 0, str(version or "v1"),
                 existing["created_at"] if existing else stamp, stamp),
            )
        return self.get(shapeId, tenantId=tenant) or {}

    def list(self, tenantId: str = "default", enabledOnly: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM ontology_shapes WHERE tenant_id = ?"
        if enabledOnly:
            sql += " AND enabled = 1"
        sql += " ORDER BY shape_id"
        with self._store._lock:
            rows = self._store._conn.execute(sql, (str(tenantId or "default"),)).fetchall()
        return [self._hydrate(r) for r in rows]

    def get(self, shapeId: str, tenantId: str = "default") -> Optional[Dict[str, Any]]:
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT * FROM ontology_shapes WHERE tenant_id = ? AND shape_id = ?",
                (str(tenantId or "default"), str(shapeId or ""))).fetchone()
        return self._hydrate(row) if row else None

    def setEnabled(self, shapeId: str, enabled: bool, tenantId: str = "default") -> None:
        with self._store._lock, self._store._conn:
            cursor = self._store._conn.execute(
                "UPDATE ontology_shapes SET enabled = ?, updated_at = ?"
                " WHERE tenant_id = ? AND shape_id = ?",
                (1 if enabled else 0, _now(), str(tenantId or "default"), str(shapeId or "")))
            if cursor.rowcount == 0:
                raise LookupError("形状不存在: %s" % shapeId)

    def delete(self, shapeId: str, tenantId: str = "default") -> None:
        with self._store._lock, self._store._conn:
            cursor = self._store._conn.execute(
                "DELETE FROM ontology_shapes WHERE tenant_id = ? AND shape_id = ?",
                (str(tenantId or "default"), str(shapeId or "")))
            if cursor.rowcount == 0:
                raise LookupError("形状不存在: %s" % shapeId)

    @staticmethod
    def _hydrate(row) -> Dict[str, Any]:
        d = dict(row)
        d["path"] = json.loads(d.pop("path_json") or "{}")
        d["constraint"] = json.loads(d.pop("constraint_json") or "{}")
        d["enabled"] = bool(d.get("enabled"))
        return d

    # ── 求值 ──────────────────────────────────────────────────

    def evaluateForRequest(self, request: Any, subjectKey: str,
                           registry: Any) -> List[Dict[str, Any]]:
        """用户 shape 的 findings（与内置校验同一 findings 流，同定位串形状）。

        逐 shape 独立判定：一个 shape 炸了只丢它自己，不影响其余 shape 与内置校验。
        """
        tenantId = str(getattr(request, "tenantId", "") or "default")
        predicate = str(getattr(request, "predicateTermId", "") or "")
        objectTerm = str(getattr(request, "objectTerm", "") or "")
        out: List[Dict[str, Any]] = []
        for shape in self.list(tenantId=tenantId, enabledOnly=True):
            if shape["target_kind"] != "relation" \
                    or shape["target_term_id"] != predicate:
                continue
            try:
                finding = self._evaluateOne(shape, request, subjectKey, objectTerm, registry)
            except Exception as exc:  # noqa: BLE001 - 单 shape 失败只丢该 shape
                out.append({"kind": "info", "rule": "shape:" + shape["shape_id"],
                            "message": "形状求值异常 %s" % exc,
                            "term_id": predicate, "subject_key": subjectKey})
                continue
            if finding is not None:
                out.append(finding)
        return out

    def _evaluateOne(self, shape: Dict[str, Any], request: Any, subjectKey: str,
                     objectTerm: str, registry: Any) -> Optional[Dict[str, Any]]:
        kind = shape["constraint_kind"]
        constraint = shape["constraint"]
        predicate = str(getattr(request, "predicateTermId", "") or "")
        finding = {"kind": shape["severity"], "rule": "shape:" + shape["shape_id"],
                   "message": shape["message"] or ("形状 %s 未满足" % shape["shape_id"]),
                   "term_id": predicate, "subject_key": subjectKey}

        if kind == "in":
            allowed = [str(v) for v in constraint.get("values") or []]
            if objectTerm not in allowed:
                return finding
            return None
        if kind == "pattern":
            pattern = str(constraint.get("pattern") or "")
            if pattern and not re.match(pattern, objectTerm):
                return finding
            return None
        if kind == "class":
            classTerm = str(constraint.get("class") or "")
            objectType = registry.subjectType(subjectKey) if subjectKey else None
            if classTerm and objectType is not None \
                    and not registry.matchesDomain(objectType, [classTerm], tenantId=shape["tenant_id"]):
                return finding
            return None
        if kind in ("minCount", "maxCount"):
            agentId = str(getattr(request, "agentId", "") or "")
            limit = int(constraint.get(kind) or 0)
            facts = registry.activeFactsForPredicate(agentId, subjectKey, predicate) \
                if subjectKey else []
            others = [f for f in facts
                      if str(f.get("object_term")) != objectTerm]
            if kind == "minCount" and len(others) + 1 < limit:
                return finding
            if kind == "maxCount" and len(others) + 1 > limit:
                return finding
            return None
        return None
