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

# v12：值域可以按**类别**声明（`range_kinds`），于是"客体必须是已登记的 concept"这类
# 约束随类型表增长自动跟随。v8 已发布、其 SQL 文本永不改写（零停机迁移纪律），
# 所以新列另起一版，由 ALTER 补上。
_SCHEMA_V12 = """
ALTER TABLE ontology_terms ADD COLUMN range_kinds TEXT NOT NULL DEFAULT '[]';
"""

# 两个由结构层固定的谓词：
# - `documented_as`：条目叙述（019b-1），基数天然不限——同一主体可以有很多份文档；
# - `is_a`：类型断言（工单 020），客体是**已登记的 concept 术语**。
# `is_a` 的值域不写死在注册表里，而是由 `_declaredKinds` 声明为 `concept` 这一类：
# 类型是数据，值域也是数据；写死一串概念 id，加一种类型就得多改一次表。
#
# 不登记它们就等于让走咽喉的谓词处在"未登记"态，读数说不清是漏检还是免检。
_SEED_TERMS: List[Dict[str, Any]] = [
    {"termId": "documented_as", "kind": "relation", "label": "被记载为", "cardinality": None},
    {"termId": IS_A_PREDICATE, "kind": "relation", "label": "是一个", "cardinality": None,
     "rangeKinds": ["concept"]},
]

# 值域可以按**类别**声明：`range_kinds` 里的每一类都展开成"当前表里该类的全部术语"。
# 于是 `is_a` 的客体合法性随类型表增长自动跟随，不需要人再同步一次。
_RANGE_KINDS = ("concept", "relation", "property")


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
                 rangeTerms: Optional[List[str]] = None, rangeKinds: Optional[List[str]] = None,
                 cardinality: Optional[int] = None,
                 disjointWith: Optional[List[str]] = None,
                 requiredProps: Optional[List[str]] = None,
                 version: str = "v1") -> Dict[str, Any]:
        """登记/更新一个术语。非法结构在**写入处**就拒，不留到查询时才炸。

        `rangeKinds` 按类别声明值域（如 `["concept"]` = 客体必须是已登记的概念术语）；
        `rangeTerms` 逐个点名。两者并存时取并集——它们说的是同一件事的两种粒度。
        """
        termId = str(termId or "").strip()
        if not termId:
            raise ValueError("term_id 不能为空")
        if kind not in _TERM_KINDS:
            raise ValueError("未知术语类别 %r（有效值: %s）" % (kind, "/".join(_TERM_KINDS)))
        for declared in rangeKinds or []:
            if declared not in _RANGE_KINDS:
                raise ValueError(
                    "未知值域类别 %r（有效值: %s）" % (declared, "/".join(_RANGE_KINDS)))
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
                " domain_terms, range_terms, range_kinds, cardinality, disjoint_with, required_props,"
                " version, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (termId, kind, label or termId, parentTermId,
                 json.dumps(list(domain or []), ensure_ascii=False),
                 json.dumps(list(rangeTerms or []), ensure_ascii=False),
                 json.dumps(sorted({str(k) for k in (rangeKinds or [])}), ensure_ascii=False),
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
                rangeKinds=spec.get("rangeKinds"),
                cardinality=spec.get("cardinality"), disjointWith=spec.get("disjointWith"),
                requiredProps=spec.get("requiredProps"), version=spec.get("version", "v1"),
            )
        return len(terms)

    def seedMissing(self, terms: List[Dict[str, Any]]) -> int:
        """**只补缺**的批量写入：已存在的术语一行都不动，返回真正补上的条数。

        与 `register`/`registerMany` 的分工必须分清：那两个是"更新"动词（写入方
        表达意图），本方法是"补齐"（播种默认值）。构造期每次都走更新语义，
        就会把写入方登记过的 domain/range/cardinality 覆盖回默认裸值——
        实测：给谓词登记了定义域，重新构造一次注册表，域就没了，
        于是本体硬拒永远无依据可判（Issue #72 附带根因）。
        """
        added = 0
        for spec in terms:
            termId = str(spec.get("termId") or spec.get("term_id") or "").strip()
            if not termId or self.term(termId) is not None:
                continue
            self.register(
                termId, spec["kind"],
                label=spec.get("label", ""), parentTermId=spec.get("parentTermId"),
                domain=spec.get("domain"), rangeTerms=spec.get("rangeTerms"),
                cardinality=spec.get("cardinality"), disjointWith=spec.get("disjointWith"),
                requiredProps=spec.get("requiredProps"), version=spec.get("version", "v1"),
            )
            added += 1
        return added

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
        for key in ("domain_terms", "range_terms", "range_kinds", "disjoint_with", "required_props"):
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
        """谓词的值域：点名的那几个 + 按类别展开出来的那一批。

        `is_a` 只声明 `rangeKinds: ["concept"]`，于是加一种概念类型不需要动 `is_a` 一行；
        展开在读取时做，表里那一行保持声明形状。
        """
        term = self.term(termId) or {}
        declared = list(term.get("range_terms") or [])
        for kind in term.get("range_kinds") or []:
            declared.extend(t["term_id"] for t in self.terms(kind))
        return sorted(set(declared))

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


def legacyGraphTerms() -> List[Dict[str, Any]]:
    """图谱那两个 Enum 的值一次性收编成表里的行（工单 018）。

    收编之后枚举退成**读兼容层**：加一种类型是往表里 INSERT 一行，不是改 Python 发一版。
    两个枚举都有 `custom`，而术语 id 是全表唯一的——它是"认不出的兜底标记"，不是一种类型，
    所以两边都不进表：进表就等于让一个 concept 和一个 relation 抢同一个 id。
    惰性导入是刻意的——知识层不在 import 期拽住认知层，且这里只读值不读行为。
    """
    from neurova.cognitive_layers.knowledge_graph.manager import NodeType, RelationType

    def _values(enumCls):
        return [t.value for t in enumCls if t.value != "custom"]

    return ([{"termId": v, "kind": "concept", "label": v} for v in _values(NodeType)]
            + [{"termId": v, "kind": "relation", "label": v} for v in _values(RelationType)])


def seedBuiltinTerms(registry: "OntologyTermRegistry") -> int:
    """补齐咽喉固定的谓词与图谱遗留类型；**已登记的行一律不动**。

    走 `seedMissing` 而不是 `registerMany`：播种的语义是"缺什么补什么"，
    而 `register` 那套是 INSERT OR REPLACE。用后者意味着每次构造注册表都把
    写入方登记过的 domain/range/cardinality 抹掉，本体硬拒随之无依据可判。

    顺序仍是"先 legacy 后显式种子"：新库里 `is_a` 两边都有，先写的那份留着，
    后写的被跳过——所以种子表排在后面这件事只在"legacy 里没有它"时才起作用；
    这正是只补缺该有的形状（谁先登记谁定，不被默认值覆盖）。
    """
    return registry.seedMissing(legacyGraphTerms() + _SEED_TERMS)
