"""本体术语注册表（工单 020，G08）：类型系统是数据，不是 Python 里的 Enum。

G08 的形状：`NodeType` / `RelationType` 两个 Enum 长在代码里，加一种类型就要改源码、
发一次版；而入库时对类型什么都不校验，脏事实直接进底座。本模块把"有哪些概念/关系、
谁的父类是谁、定义域值域是什么、基数几、谁与谁不相交、必填属性有哪些"变成表里的行，
校验（`validation.py`）与推理（021）都读同一张表。

一条刻意的保守：**未登记的术语不算违规，只算"这一维没依据"**。拿"没登记"当"不合法"，
等于让注册表的覆盖率决定写入是否可用——那是把治理做成随机拒绝。未登记面由
`unregisteredFindings()` 如实报出，供巡检与 018 的枚举收编用。
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Dict, List, Optional

_TERM_KINDS = ("concept", "relation", "property")

# 类型断言的固定谓词：`is_a` 是"这条主体是什么"的写法，与 `documented_as` 一样
# 由结构层固定，不让每个写入方自造一个"属于类型"谓词。
IS_A_PREDICATE = "is_a"

_SCHEMA_V8 = """
CREATE TABLE IF NOT EXISTS ontology_terms (
    term_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    parent_term_id TEXT,
    domain_terms TEXT NOT NULL DEFAULT '[]',
    range_terms TEXT NOT NULL DEFAULT '[]',
    cardinality INTEGER,
    disjoint_with TEXT NOT NULL DEFAULT '[]',
    required_props TEXT NOT NULL DEFAULT '[]',
    version TEXT NOT NULL DEFAULT 'v1',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ontology_parent ON ontology_terms(parent_term_id);
CREATE INDEX IF NOT EXISTS idx_ontology_kind ON ontology_terms(kind);
"""

# 条目叙述的谓词由咽喉固定（`documented_as`），基数天然不限：同一主体可以有很多份文档。
# 不登记它就等于让第一个走咽喉的谓词处在"未登记"态，读数说不清是漏检还是免检。
_SEED_TERMS: List[Dict[str, Any]] = [
    {"termId": "documented_as", "kind": "relation", "label": "被记载为", "cardinality": None},
    {"termId": IS_A_PREDICATE, "kind": "relation", "label": "是一个", "cardinality": None},
]


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class OntologyTermRegistry:
    """`ontology_terms` 的唯一读写面。所有查询都吃得住"没登记"这一态。"""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._ensureTable()
        seedBuiltinTerms(self)

    # ── 结构 ──────────────────────────────────────────────────

    def _ensureTable(self) -> None:
        from ..foundation.foundation_schema import applyTo

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    def _conn(self):
        return self._store._conn

    # ── 写 ────────────────────────────────────────────────────

    def register(self, termId: str, kind: str, *, label: str = "",
                 parentTermId: Optional[str] = None, domain: Optional[List[str]] = None,
                 rangeTerms: Optional[List[str]] = None, cardinality: Optional[int] = None,
                 disjointWith: Optional[List[str]] = None,
                 requiredProps: Optional[List[str]] = None,
                 version: str = "v1") -> Dict[str, Any]:
        """登记/更新一个术语。非法结构在**写入处**就拒，不留到查询时才炸。"""
        termId = str(termId or "").strip()
        if not termId:
            raise ValueError("term_id 不能为空")
        if kind not in _TERM_KINDS:
            raise ValueError("未知术语类别 %r（有效值: %s）" % (kind, "/".join(_TERM_KINDS)))
        if parentTermId == termId:
            raise ValueError("术语不能是自己的父类: %s" % termId)
        if cardinality is not None and int(cardinality) < 1:
            raise ValueError("cardinality 至少为 1（不限请传 None），收到 %r" % cardinality)
        if parentTermId and kind != "concept":
            raise ValueError("只有 concept 能有父类，%s 是 %s" % (termId, kind))
        if parentTermId and not self.term(parentTermId):
            raise ValueError("父类未登记: %s（先登记父类，别留悬空边）" % parentTermId)
        stamp = _now()
        with self._store._lock, self._store._conn:
            existing = self._store._conn.execute(
                "SELECT created_at FROM ontology_terms WHERE term_id = ?", (termId,)).fetchone()
            self._store._conn.execute(
                "INSERT OR REPLACE INTO ontology_terms (term_id, kind, label, parent_term_id,"
                " domain_terms, range_terms, cardinality, disjoint_with, required_props,"
                " version, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (termId, kind, label or termId, parentTermId,
                 json.dumps(list(domain or []), ensure_ascii=False),
                 json.dumps(list(rangeTerms or []), ensure_ascii=False),
                 cardinality,
                 json.dumps(sorted({str(d) for d in (disjointWith or [])}), ensure_ascii=False),
                 json.dumps(list(requiredProps or []), ensure_ascii=False),
                 version, existing["created_at"] if existing else stamp, stamp),
            )
        return self.term(termId) or {}

    def registerMany(self, terms: List[Dict[str, Any]]) -> int:
        """批量登记（018 收编枚举值、以及"加类型不改 .py"的入口都是这里）。"""
        for spec in terms:
            self.register(
                spec.get("termId") or spec.get("term_id"), spec["kind"],
                label=spec.get("label", ""), parentTermId=spec.get("parentTermId"),
                domain=spec.get("domain"), rangeTerms=spec.get("rangeTerms"),
                cardinality=spec.get("cardinality"), disjointWith=spec.get("disjointWith"),
                requiredProps=spec.get("requiredProps"), version=spec.get("version", "v1"),
            )
        return len(terms)

    def assignSubjectType(self, subjectKey: str, termId: str) -> None:
        """给主体挂类型。类型没登记就拒——挂一个不存在的类型比不挂更糟。"""
        if not self.term(termId):
            raise ValueError("类型未登记: %s" % termId)
        with self._store._lock, self._store._conn:
            cur = self._store._conn.execute(
                "UPDATE knowledge_subjects SET type_term_id = ?, updated_at = ?"
                " WHERE subject_key = ?", (termId, _now(), subjectKey))
            if cur.rowcount == 0:
                raise LookupError("主体不存在: %s" % subjectKey)

    # ── 读 ────────────────────────────────────────────────────

    def term(self, termId: Optional[str]) -> Optional[Dict[str, Any]]:
        if not termId:
            return None
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT * FROM ontology_terms WHERE term_id = ?", (termId,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        for key in ("domain_terms", "range_terms", "disjoint_with", "required_props"):
            d[key] = json.loads(d[key] or "[]")
        return d

    def terms(self, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT term_id FROM ontology_terms"
        params: List[Any] = []
        if kind:
            sql += " WHERE kind = ?"
            params.append(kind)
        with self._store._lock:
            ids = [r["term_id"] for r in
                   self._store._conn.execute(sql + " ORDER BY term_id", params).fetchall()]
        return [self.term(i) for i in ids if self.term(i)]

    def isSubtypeOf(self, termId: str, ancestorId: str, _seen: Optional[set] = None) -> bool:
        seen = _seen or set()
        if termId in seen:
            return False          # 环不追（结构上 register 已挡自父，跨三条以上才可能绕回来）
        seen.add(termId)
        current = self.term(termId)
        while current and current.get("parent_term_id"):
            parent = current["parent_term_id"]
            if parent == ancestorId:
                return True
            current = self.term(parent)
        return False

    def matchesDomain(self, termId: str, domainTerms: List[str]) -> bool:
        return any(termId == d or self.isSubtypeOf(termId, d) for d in domainTerms)

    def maxCardinality(self, termId: str) -> Optional[int]:
        term = self.term(termId)
        return term.get("cardinality") if term else None

    def domainOf(self, termId: str) -> List[str]:
        term = self.term(termId) or {}
        return list(term.get("domain_terms") or [])

    def rangeOf(self, termId: str) -> List[str]:
        term = self.term(termId) or {}
        return list(term.get("range_terms") or [])

    def disjointWith(self, termId: str) -> List[str]:
        term = self.term(termId) or {}
        return list(term.get("disjoint_with") or [])

    def requiredProps(self, termId: str) -> List[str]:
        term = self.term(termId) or {}
        return list(term.get("required_props") or [])

    def assertedTypesOf(self, agentId: str, subjectKey: str) -> List[str]:
        """主体被断言过的全部类型：列上那一个 + 所有 `is_a` 事实的客体。

        一个 `type_term_id` 列装不下"既是 A 又是 B"，而不相交判定要的正是这个同时性。
        """
        types: List[str] = []
        single = self.subjectType(subjectKey)
        if single:
            types.append(single)
        with self._store._lock:
            rows = self._store._conn.execute(
                "SELECT object_term FROM knowledge_facts WHERE agent_id = ?"
                " AND subject_key = ? AND predicate_term_id = ? AND status = 'active'",
                (agentId, subjectKey, IS_A_PREDICATE)).fetchall()
        types.extend(r["object_term"] for r in rows)
        return sorted(set(types))

    def subjectType(self, subjectKey: str) -> Optional[str]:
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT type_term_id FROM knowledge_subjects WHERE subject_key = ?",
                (subjectKey,)).fetchone()
        return row["type_term_id"] if row and row["type_term_id"] else None

    def activeFactsForPredicate(self, agentId: str, subjectKey: str,
                                predicateTermId: str) -> List[Dict[str, Any]]:
        with self._store._lock:
            rows = self._store._conn.execute(
                "SELECT * FROM knowledge_facts WHERE agent_id = ? AND subject_key = ?"
                " AND predicate_term_id = ? AND status = 'active'",
                (agentId, subjectKey, predicateTermId)).fetchall()
        return [self._store._hydrate(r) for r in rows]

    def subjectKeysOfType(self, agentId: str, termIds: List[str]) -> List[str]:
        if not termIds:
            return []
        placeholders = ",".join("?" * len(termIds))
        with self._store._lock:
            rows = self._store._conn.execute(
                "SELECT subject_key FROM knowledge_subjects"
                " WHERE agent_id = ? AND type_term_id IN (%s)" % placeholders,
                [agentId] + list(termIds)).fetchall()
        return [r["subject_key"] for r in rows]

    def termCount(self) -> int:
        with self._store._lock:
            return self._store._conn.execute(
                "SELECT COUNT(*) FROM ontology_terms").fetchone()[0]


def seedBuiltinTerms(registry: "OntologyTermRegistry") -> int:
    """登记咽喉自己固定的谓词（幂等：registerMany 是 INSERT OR REPLACE）。"""
    return registry.registerMany(_SEED_TERMS)
