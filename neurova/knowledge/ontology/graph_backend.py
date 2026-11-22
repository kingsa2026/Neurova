# -*- coding: utf-8 -*-
"""可插拔图后端门面（U8，specs/2026-11-22 参照系 ae 计划 D-U4）。

本体域的图数据此前锁死 SQLite 单后端：事实行由 admission 咽喉写进
`KnowledgeFactStore`（`knowledge_facts` active triple），投影/导出面直接吃
`store._conn` 的行。本模块把「图数据的读/写」收成一个**最小契约**
（`GraphBackend`），能力面从真实消费路径反推，不凭空造大接口：

- `conceptTerms(tenantId)` —— 概念术语行，导出面节点来源
  （`export/graph_exchange._readGraph` 的 termRows）；
- `activeTriples(tenantId, agentId)` —— active triple 行（含主体规范名），
  导出面边来源（同上 factRows）；
- `writeConceptTerm` / `writeTriple` —— 存储层写原语：sqlite 档委托
  `OntologyTermRegistry.register` 与 `store.upsertSubject`+`upsertFact`
  （既有公开原语，不另造第二份写路径）；治理面（断言/校验/冲突裁决）
  仍唯一走 admission，门面不承担治理。

两个实现：

- `SQLiteBackend`：既有 `KnowledgeFactStore` 的薄包装，**唯一默认生产实现**，
  读行与既有 SQL 逐行一致（行为逐字节保持）；
- `OxigraphBackend`：pyoxigraph 嵌入式 RDF 库（可选依赖，惰性 import＋
  fail-soft）——同一契约的独立实现，仅作可插拔能力证明。

`resolveGraphBackend()` 按 `NEUROVA_ONTOLOGY_GRAPH_BACKEND` 解析：
缺省/`sqlite` 恒回 SQLite；`oxigraph` 未安装时显式
`GraphBackendNotSupported`（不静默降级回 sqlite）；未知值显式 `ValueError`。
**默认绝不切换**——不设该环境变量时全仓行为与单后端时代逐字节一致。
"""

from __future__ import annotations

import hashlib
import os
import threading
from typing import Any, Dict, List, Optional, Protocol
from urllib.parse import quote, unquote

from neurova.core.tenant_scope import tenant_sql_where

#: 后端选择环境变量（缺省 sqlite）
GRAPH_BACKEND_ENV = "NEUROVA_ONTOLOGY_GRAPH_BACKEND"
#: 缺省后端——SQLite 永远是默认生产实现
DEFAULT_GRAPH_BACKEND = "sqlite"
#: 合法取值闭集
ALLOWED_GRAPH_BACKENDS = ("sqlite", "oxigraph")

# OxigraphBackend 的内部存储编码（实现细节，不出契约）：
# 三元组与元数据（主体规范名/术语类别）分前缀命名空间，租户/agent 域
# 用命名图承载——与 sqlite 侧行级 tenant_id/agent_id 过滤同语义。
_OX_BASE = "https://neurova.local/knowledge/backend/"
_OX_TERM_NS = _OX_BASE + "term/"
_OX_SUBJECT_NS = _OX_BASE + "subject/"
_OX_PREDICATE_NS = _OX_BASE + "predicate/"
_OX_GRAPH_NS = _OX_BASE + "graph/"
_OX_LABEL_PRED = _OX_BASE + "label"
_OX_KIND_PRED = _OX_BASE + "kind"


class GraphBackendNotSupported(RuntimeError):
    """请求的图后端不可用——显式 not_supported，不静默降级回 sqlite。"""


class GraphBackend(Protocol):
    """图数据最小契约：能力面＝真实消费方（graph_exchange 导出行来源）。"""

    def backendName(self) -> str:
        """后端标识（与注册表取值同名：sqlite / oxigraph）。"""
        ...

    def conceptTerms(self, tenantId: str = "default") -> List[Dict[str, str]]:
        """概念术语行 `{term_id, kind, label}`，按 term_id 升序；仅 kind='concept'。"""
        ...

    def activeTriples(self, tenantId: str = "default",
                      agentId: str = "") -> List[Dict[str, str]]:
        """active triple 行 `{subject_label, predicate_term_id, object_term}`。

        只收 `status='active' AND record_kind='triple'`；空 `agentId` 表示不过滤
        agent；按 (subject_label, predicate_term_id, object_term) 升序。
        """
        ...

    def writeConceptTerm(self, *, tenantId: str, termId: str, label: str,
                         kind: str = "concept") -> None:
        """登记/更新一个术语（sqlite 档委托 OntologyTermRegistry 唯一写面）。"""
        ...

    def writeTriple(self, *, tenantId: str, agentId: str, subjectLabel: str,
                    predicateTermId: str, objectTerm: str) -> str:
        """落一条三元组，回事实句柄；同 SPO 重写回同一句柄（幂等）。"""
        ...


class SQLiteBackend:
    """既有 `KnowledgeFactStore` 的薄包装——唯一默认生产实现。

    读面走 `store.queryReadOnly`（P3-6 收口的唯一外部读数门），SQL 与
    `graph_exchange._readGraph` 既有取行逐字一致，行内容逐行相同；
    写面委托 store 公开原语（`upsertSubject`/`upsertFact`）与术语注册表
    （`OntologyTermRegistry.register`），不新造任何写 SQL。store 的生命周期
    归调用方（生产＝进程级单例），本包装不 close 它。
    """

    def __init__(self, store: Any) -> None:
        if store is None:
            raise ValueError("SQLiteBackend 需显式传入 KnowledgeFactStore 实例")
        self._store = store
        self._terms: Any = None

    def backendName(self) -> str:
        return "sqlite"

    def _termRegistry(self) -> Any:
        if self._terms is None:
            from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

            self._terms = OntologyTermRegistry(self._store)
        return self._terms

    def conceptTerms(self, tenantId: str = "default") -> List[Dict[str, str]]:
        clause, params = tenant_sql_where(tenantId)
        return self._store.queryReadOnly(
            "SELECT term_id, kind, label FROM ontology_terms"
            " WHERE %s AND kind = 'concept' ORDER BY term_id" % clause,
            tuple(params))

    def activeTriples(self, tenantId: str = "default",
                      agentId: str = "") -> List[Dict[str, str]]:
        clause, params = tenant_sql_where(tenantId, alias="f")
        sql = ("SELECT s.canonical_label AS subject_label,"
               " f.predicate_term_id, f.object_term"
               " FROM knowledge_facts f JOIN knowledge_subjects s"
               " ON s.subject_key = f.subject_key"
               " WHERE %s AND f.status = 'active'"
               " AND f.record_kind = 'triple'" % clause)
        if agentId:
            sql += " AND f.agent_id = ?"
            params.append(str(agentId))
        sql += (" ORDER BY s.canonical_label, f.predicate_term_id,"
                " f.object_term")
        return self._store.queryReadOnly(sql, tuple(params))

    def writeConceptTerm(self, *, tenantId: str, termId: str, label: str,
                         kind: str = "concept") -> None:
        self._termRegistry().register(str(termId or "").strip(), str(kind or "concept"),
                                      label=str(label or ""),
                                      tenantId=str(tenantId or "default"))

    def writeTriple(self, *, tenantId: str, agentId: str, subjectLabel: str,
                    predicateTermId: str, objectTerm: str) -> str:
        tenant = str(tenantId or "default")
        agent = str(agentId or "")
        label = str(subjectLabel or "")
        subjectKey = self._store.upsertSubject(agent, label, tenantId=tenant)
        return self._store.upsertFact(
            agent, subjectKey, str(predicateTermId or ""), str(objectTerm or ""),
            "%s %s %s" % (label, predicateTermId, objectTerm), tenantId=tenant)


class OxigraphBackend:
    """pyoxigraph 嵌入式 RDF 库实现——同一契约的独立实现。

    可选依赖：构造期经 `_loadOxigraph()` 惰性 import，未安装显式
    `GraphBackendNotSupported`（不静默降级）。进程内共享一份内存库
    （`resolveGraphBackend` 以 DCL 单例提供）；租户/agent 域编码进命名图，
    与 sqlite 侧行级过滤同语义。默认档不加载本类。
    """

    def __init__(self) -> None:
        self._ox: Any = _loadOxigraph()
        self._store: Any = self._ox.Store()

    def backendName(self) -> str:
        return "oxigraph"

    def _graphIri(self, tenantId: str, agentId: str = "") -> Any:
        tenant = quote(str(tenantId or "default"), safe="")
        agent = quote(str(agentId or ""), safe="")
        return self._ox.NamedNode(_OX_GRAPH_NS + tenant + "/" + agent)

    def _termNode(self, termId: str) -> Any:
        return self._ox.NamedNode(_OX_TERM_NS + quote(str(termId or ""), safe=""))

    def _subjectNode(self, subjectLabel: str) -> Any:
        return self._ox.NamedNode(_OX_SUBJECT_NS + quote(str(subjectLabel or ""), safe=""))

    def _predicateNode(self, predicateTermId: str) -> Any:
        return self._ox.NamedNode(_OX_PREDICATE_NS + quote(str(predicateTermId or ""), safe=""))

    def _add(self, subject: Any, predicate: Any, obj: Any, graph: Any) -> None:
        self._store.add(self._ox.Quad(subject, predicate, obj, graph))

    @staticmethod
    def _graphValue(graphName: Any) -> Optional[str]:
        value = getattr(graphName, "value", None)
        return str(value) if value is not None else None

    @classmethod
    def _inScope(cls, graphName: Any, tenantId: str, agentId: str) -> bool:
        """命名图是否落在 (tenantId, agentId) 过滤域内；空值＝该维不过滤。"""
        value = cls._graphValue(graphName)
        if not value or not value.startswith(_OX_GRAPH_NS):
            return False
        tenant, _, agent = value[len(_OX_GRAPH_NS):].partition("/")
        if tenantId and unquote(tenant) != str(tenantId):
            return False
        if agentId and unquote(agent) != str(agentId):
            return False
        return True

    @staticmethod
    def _termIdOf(node: Any) -> Optional[str]:
        value = getattr(node, "value", None)
        if value and str(value).startswith(_OX_TERM_NS):
            return unquote(str(value)[len(_OX_TERM_NS):])
        return None

    @staticmethod
    def _subjectLabelOf(node: Any, labels: Dict[str, str]) -> str:
        value = str(getattr(node, "value", "") or "")
        if value in labels:
            return labels[value]
        if value.startswith(_OX_SUBJECT_NS):
            return unquote(value[len(_OX_SUBJECT_NS):])
        return value

    def conceptTerms(self, tenantId: str = "default") -> List[Dict[str, str]]:
        graph = self._graphIri(tenantId)
        kinds: Dict[str, str] = {}
        labels: Dict[str, str] = {}
        for quad in self._store.quads_for_pattern(
                None, self._ox.NamedNode(_OX_KIND_PRED), None):
            if not self._inScope(quad.graph_name, tenantId, ""):
                continue
            termId = self._termIdOf(quad.subject)
            if termId is not None:
                kinds[termId] = str(quad.object.value)
        for quad in self._store.quads_for_pattern(
                None, self._ox.NamedNode(_OX_LABEL_PRED), None):
            if not self._inScope(quad.graph_name, tenantId, ""):
                continue
            termId = self._termIdOf(quad.subject)
            if termId is not None:
                labels[termId] = str(quad.object.value)
        rows = [{"term_id": termId, "kind": kind, "label": labels.get(termId, "")}
                for termId, kind in kinds.items() if kind == "concept"]
        return sorted(rows, key=lambda row: row["term_id"])

    def activeTriples(self, tenantId: str = "default",
                      agentId: str = "") -> List[Dict[str, str]]:
        labels: Dict[str, str] = {}
        triples: List[Any] = []
        for quad in self._store.quads_for_pattern(None, None, None):
            if not self._inScope(quad.graph_name, tenantId, agentId):
                continue
            predicate = str(quad.predicate.value)
            if predicate == _OX_LABEL_PRED:
                labels[str(quad.subject.value)] = str(quad.object.value)
            elif predicate.startswith(_OX_PREDICATE_NS):
                triples.append(quad)
        rows = [{"subject_label": self._subjectLabelOf(quad.subject, labels),
                 "predicate_term_id": unquote(
                     str(quad.predicate.value)[len(_OX_PREDICATE_NS):]),
                 "object_term": str(quad.object.value)}
                for quad in triples]
        return sorted(rows, key=lambda row: (row["subject_label"],
                                             row["predicate_term_id"],
                                             row["object_term"]))

    def writeConceptTerm(self, *, tenantId: str, termId: str, label: str,
                         kind: str = "concept") -> None:
        graph = self._graphIri(tenantId)
        term = self._termNode(termId)
        self._add(term, self._ox.NamedNode(_OX_KIND_PRED),
                  self._ox.Literal(str(kind or "concept")), graph)
        self._add(term, self._ox.NamedNode(_OX_LABEL_PRED),
                  self._ox.Literal(str(label or "")), graph)

    def writeTriple(self, *, tenantId: str, agentId: str, subjectLabel: str,
                    predicateTermId: str, objectTerm: str) -> str:
        tenant = str(tenantId or "default")
        agent = str(agentId or "")
        label = str(subjectLabel or "")
        predicate = str(predicateTermId or "")
        obj = str(objectTerm or "")
        graph = self._graphIri(tenant, agent)
        subject = self._subjectNode(label)
        self._add(subject, self._predicateNode(predicate), self._ox.Literal(obj),
                  graph)
        self._add(subject, self._ox.NamedNode(_OX_LABEL_PRED),
                  self._ox.Literal(label), graph)
        digest = hashlib.sha256("|".join((tenant, agent, label, predicate, obj))
                                .encode("utf-8")).hexdigest()[:16]
        return "ox_%s" % digest


def _loadOxigraph() -> Any:
    """惰性装载 pyoxigraph；未安装显式 not_supported（fail-soft 形态）。"""
    try:
        import pyoxigraph
    except ImportError as exc:
        raise GraphBackendNotSupported(
            "pyoxigraph 未安装：图后端 %s=oxigraph 显式 not_supported"
            "（可选依赖，pip install pyoxigraph；默认 sqlite 档不受影响）"
            % GRAPH_BACKEND_ENV) from exc
    return pyoxigraph


_oxigraph_singleton: Optional[OxigraphBackend] = None
_oxigraph_lock = threading.Lock()


def resolveGraphBackend(store: Any = None) -> GraphBackend:
    """按环境变量解析图后端；缺省恒为 sqlite（默认绝不切换）。

    - 缺省 / `sqlite`（大小写与首尾空白不敏感）→ `SQLiteBackend`：
      `store` 缺省时接生产事实底座单例；
    - `oxigraph` → 进程级 `OxigraphBackend` 单例（DCL）；pyoxigraph 未安装
      显式 `GraphBackendNotSupported`；
    - 其余取值显式 `ValueError`（列出合法闭集），不静默回退。
    """
    choice = str(os.environ.get(GRAPH_BACKEND_ENV) or "").strip().lower() \
        or DEFAULT_GRAPH_BACKEND
    if choice == "sqlite":
        if store is None:
            from neurova.knowledge.foundation.knowledge_facts import (
                get_knowledge_fact_store,
            )

            store = get_knowledge_fact_store()
        return SQLiteBackend(store)
    if choice == "oxigraph":
        return _oxigraphSingleton()
    raise ValueError(
        "未知图后端 %r：%s 只认 %s（缺省 %s）"
        % (choice, GRAPH_BACKEND_ENV, "/".join(ALLOWED_GRAPH_BACKENDS),
           DEFAULT_GRAPH_BACKEND))


def _oxigraphSingleton() -> OxigraphBackend:
    global _oxigraph_singleton
    if _oxigraph_singleton is None:
        with _oxigraph_lock:
            if _oxigraph_singleton is None:
                _oxigraph_singleton = OxigraphBackend()
    return _oxigraph_singleton


__all__ = [
    "ALLOWED_GRAPH_BACKENDS",
    "DEFAULT_GRAPH_BACKEND",
    "GRAPH_BACKEND_ENV",
    "GraphBackend",
    "GraphBackendNotSupported",
    "OxigraphBackend",
    "SQLiteBackend",
    "resolveGraphBackend",
]
