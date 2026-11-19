# -*- coding: utf-8 -*-
"""schema 目录 → 本体术语/关系建议器（对照研究 P1-2，2026-11-15）。

从 P1-1 的 schema 目录自动产出**候选**（不直接落本体）：

- 术语建议（kind=term）：表 → 业务概念命名 + 描述 + 同义词 + 列显示名。
  确定性基线（humanize 表名）永远可用；给了 llm_call 才做 LLM 精化，
  LLM 失败/畸形输出回退确定性结果（不吞成空建议）。
- 关系候选：外键边（目录声明键 + 命名规约推断 `*_id`）进**既有**
  `ontology_relation_candidates` 审批流（B8 面不另造第二审批表）；
  命名规约推断的边可选做 join 探针数据证实（probe，按源显式开），
  证实后置信度上调、payload 记 confirmed_by。

治理纪律：机器只产候选，术语登记只发生在审批通过时（走注册表单点）；
被拒目标不再重新生成（人工否决是决定，不是噪声）。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Callable, Dict, List, Optional

from neurova.core.time_utils import nowIso as _now

#: v52：schema 建议表。关系候选不在此表（复用 ontology_relation_candidates）。
_SCHEMA_V52_SUGGESTIONS = """
CREATE TABLE IF NOT EXISTS ontology_schema_suggestions (
    suggestion_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    source_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'term',
    target TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    basis TEXT NOT NULL DEFAULT 'rule',
    confidence REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    reviewed_by TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_schema_suggestions_review
    ON ontology_schema_suggestions(tenant_id, status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_schema_suggestions_target
    ON ontology_schema_suggestions(tenant_id, source_id, kind, target);
"""

_SUGGESTION_STATUSES = ("pending", "approved", "rejected")

#: v54（对照研究 P3-1a，2026-11-19）：审批决策绑定证据内容哈希——建议生成时
#: 记下 payload_json 的 sha256 截断，人工审批请求必须回带同一哈希。
#: 存量行为空串：不带哈希放行（兼容），带哈希按不匹配拒。
_SCHEMA_V54_SUGGESTION_EVIDENCE = """
ALTER TABLE ontology_schema_suggestions
    ADD COLUMN evidence_hash TEXT NOT NULL DEFAULT '';
"""

_LLM_ENRICH_PROMPT = """你是数据目录编辑。根据表名与列清单给出业务概念命名。
输出严格 JSON（不要解释）：
{{"name": "业务概念名（如 Sales Order）", "description": "一句话业务定义",
  "synonyms": ["同义词"], "columns": [{{"column": "物理列名", "display_name": "显示名"}}]}}
约束：columns 必须覆盖给出的每个物理列，display_name 用业务词（空格分隔）。
表名：{table}
列：{columns}"""

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)
_TOKEN_SPLIT = re.compile(r"[\W_]+", re.UNICODE)
#: 命名规约外键列：xxx_id；本体词形归一后与既有表名比对
_FK_COLUMN_RE = re.compile(r"^(?P<base>.+)_id$", re.IGNORECASE)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


def parseLlmJson(text: str) -> Optional[Dict[str, Any]]:
    """解析 LLM 输出中的 JSON 对象（容忍 markdown 围栏；不可信输入 → None）。"""
    if not text:
        return None
    match = _FENCE_RE.search(text)
    raw = match.group(1) if match else text
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except Exception:  # noqa: BLE001 - LLM 输出不可信
        return None
    return data if isinstance(data, dict) else None


def humanizeTableName(tableName: str) -> str:
    """`sales_orders` → "Sales Orders"（确定性命名基线，无 LLM 也成立）。"""
    parts = [p for p in _TOKEN_SPLIT.split(str(tableName or "")) if p]
    return " ".join(p[:1].upper() + p[1:] for p in parts)


def _slugTermId(name: str) -> str:
    parts = [p for p in _TOKEN_SPLIT.split(str(name or "")) if p]
    return "".join(p[:1].upper() + p[1:] for p in parts) or "SchemaTerm"


def _inferFkEdges(tables: List[Dict[str, Any]],
                  declaredEdges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """外键边 = 目录声明键（confidence 0.6）＋ 命名规约推断（0.4，去重）。

    推断口径：列名 `xxx_id`，剥离 `_id` 后与同源某表名（含复数/下划线归一）
    匹配，且不是该表自己的主键自引用。
    """
    edges: List[Dict[str, Any]] = []
    seen: set = set()
    tableNames = {str(t.get("table_name") or "") for t in tables}
    normalizedTables = {re.sub(r"[\W_]+", "", n.lower()): n for n in tableNames}
    for edge in declaredEdges:
        key = (edge.get("source_table"), edge.get("source_column"),
               edge.get("target_table"), edge.get("target_column"))
        if key not in seen:
            seen.add(key)
            edges.append({**edge, "declared": True, "confidence": 0.6})
    for table in tables:
        tableName = str(table.get("table_name") or "")
        for column in table.get("columns") or []:
            columnName = str(column.get("column_name") or "")
            match = _FK_COLUMN_RE.match(columnName)
            if not match:
                continue
            base = re.sub(r"[\W_]+", "", match.group("base").lower())
            targetTable = normalizedTables.get(base)
            if not targetTable or targetTable == tableName:
                continue  # 无对应表 / 自引用不推断
            key = (tableName, columnName, targetTable, "id")
            if key in seen:
                continue
            seen.add(key)
            edges.append({"source_table": tableName, "source_column": columnName,
                          "target_table": targetTable, "target_column": "",
                          "declared": False, "confidence": 0.4})
    return edges


class SchemaSuggester:
    """schema 目录 → 术语/关系候选的唯一产出面。"""

    def __init__(self, store: Any, catalog: Any = None,
                 relationCandidates: Any = None, termRegistry: Any = None) -> None:
        self._store = store
        if catalog is None:
            from ..enterprise.schema_catalog import SchemaCatalogStore

            catalog = SchemaCatalogStore(store)
        self._catalog = catalog
        if relationCandidates is None:
            from .relation_candidates import RelationCandidateStore

            relationCandidates = RelationCandidateStore(store)
        self._relations = relationCandidates
        if termRegistry is None:
            from .term_registry import OntologyTermRegistry

            termRegistry = OntologyTermRegistry(store)
        self._terms = termRegistry
        from ..foundation.foundation_schema import applyTo

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    # ── 产出 ────────────────────────────────────────────────

    def runForSource(self, tenantId: str, sourceId: str, llmCall: Optional[Callable[[str], str]] = None,
                     probeRunner: Optional[Callable[[str], List[Dict[str, Any]]]] = None
                     ) -> Dict[str, Any]:
        """对单个源跑一轮建议：术语建议落 suggestions 表，关系候选进审批流。

        probeRunner：可选只读探针执行器（端点层由适配器 executeReadonly 构造）；
        给了才对**命名规约推断**的外键边做 join 探针证实，失败/不可用如实降级。
        """
        tenant = str(tenantId or "default")
        source = str(sourceId or "")
        tables = self._catalog.listTables(tenant, sourceId=source, limit=10000)
        declaredEdges = self._catalog.foreignKeyEdges(tenant, sourceId=source)
        # listTables 行不带列集；推断与命名都要列，逐表取一次明细
        tableViews: List[Dict[str, Any]] = []
        for table in tables:
            detail = self._catalog.tableDetail(tenant, str(table["catalog_table_id"])) or {}
            tableViews.append({**table, "columns": list(detail.get("columns") or [])})
        termsCreated = 0
        relationsCreated = 0
        probesConfirmed = 0
        for table in tableViews:
            tableName = str(table["table_name"])
            target = "term:%s:%s" % (source, tableName)
            if self._hasActiveSuggestion(tenant, source, "term", target):
                continue
            payload = self._termPayload(table, llmCall)
            self._recordSuggestion(tenant, source, "term", target, payload,
                                   basis=payload.pop("_basis", "rule"),
                                   confidence=payload.pop("_confidence", 0.5))
            termsCreated += 1
        for edge in _inferFkEdges(tableViews, declaredEdges):
            surface = humanizeTableName(
                re.sub(r"_id$", "", str(edge["source_column"]), flags=re.IGNORECASE))
            sourceEntryId = "catalog:%s:%s:%s" % (source, edge["source_table"],
                                                  edge["source_column"])
            sourceText = "%s.%s → %s%s（%s）" % (
                edge["source_table"], edge["source_column"], edge["target_table"],
                "." + str(edge["target_column"]) if edge.get("target_column") else "",
                "声明外键" if edge.get("declared") else "命名规约推断")
            confidence = float(edge.get("confidence") or 0.4)
            if probeRunner is not None and not edge.get("declared"):
                confirmed = self._probeEdge(probeRunner, edge)
                if confirmed:
                    confidence = 0.75
                    probesConfirmed += 1
                    sourceText += "；join 探针证实"
            candidateId = self._relations.record(
                tenant, surface, sourceEntryId=sourceEntryId,
                sourceText=sourceText, confidence=confidence)
            if candidateId:
                relationsCreated += 1
        return {"source_id": source, "term_suggestions": termsCreated,
                "relation_candidates": relationsCreated,
                "probes_confirmed": probesConfirmed}

    def runForAllSources(self, tenantId: str, llmCall: Optional[Callable[[str], str]] = None,
                         probeRunnerFactory: Optional[Callable[[str], Any]] = None,
                         maxWorkers: int = 3) -> Dict[str, Any]:
        """全源并行跑建议（P3-3 有界并行：worker 异常逐项隔离，结果按序回收）。"""
        from .compile_kit import runBounded

        tenant = str(tenantId or "default")
        sources = self._catalog.sourcesInCatalog(tenant)
        summaries: List[Dict[str, Any]] = []

        def _worker(sourceId: str, _position: int) -> Dict[str, Any]:
            probeRunner = None
            if probeRunnerFactory is not None:
                probeRunner = probeRunnerFactory(sourceId)
            return self.runForSource(tenant, sourceId, llmCall=llmCall,
                                     probeRunner=probeRunner)

        outcome = runBounded(sources, _worker, maxWorkers=maxWorkers,
                             onResult=summaries.append)
        return {"sources": summaries, "errors": outcome["errors"]}

    # ── 审批 ────────────────────────────────────────────────

    def listSuggestions(self, tenantId: str, status: str = "pending",
                        sourceId: str = "", kind: str = "",
                        limit: int = 100) -> List[Dict[str, Any]]:
        if status not in _SUGGESTION_STATUSES:
            raise ValueError("未知建议状态 %r（有效值: %s）"
                             % (status, " / ".join(_SUGGESTION_STATUSES)))
        sql = "SELECT * FROM ontology_schema_suggestions WHERE tenant_id = ? AND status = ?"
        params: List[Any] = [str(tenantId or "default"), status]
        if sourceId:
            sql += " AND source_id = ?"
            params.append(str(sourceId))
        if kind:
            sql += " AND kind = ?"
            params.append(str(kind))
        sql += " ORDER BY created_at, suggestion_id LIMIT ?"
        params.append(max(1, int(limit)))
        with self._store._lock:
            rows = self._store._conn.execute(sql, tuple(params)).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["payload"] = json.loads(d.pop("payload_json", "{}") or "{}")
            out.append(d)
        return out

    def decideSuggestion(self, tenantId: str, suggestionId: str, decision: str,
                         reviewedBy: str = "", evidenceHash: str = "") -> Dict[str, Any]:
        """人工处置：approved 落术语并回填目录链接；rejected 留审计不再重生。

        证据哈希绑定（P3-1a）：建议带 evidence_hash 时审批请求必须回带同一哈希。
        """
        if decision not in ("approved", "rejected"):
            raise ValueError("decision 只允许 approved|rejected，收到 %r" % decision)
        tenant = str(tenantId or "default")
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT * FROM ontology_schema_suggestions"
                " WHERE tenant_id = ? AND suggestion_id = ?",
                (tenant, str(suggestionId or ""))).fetchone()
        if row is None:
            raise LookupError("建议不存在: %s" % suggestionId)
        if row["status"] != "pending":
            raise ValueError("建议 %s 已是 %s 态，不能重复审批"
                             % (suggestionId, row["status"]))
        expectedHash = str(row["evidence_hash"] or "") if "evidence_hash" in row.keys() else ""
        if expectedHash:
            got = str(evidenceHash or "").strip()
            if not got:
                raise ValueError(
                    "建议 %s 绑定了证据哈希，审批请求必须回带 evidence_hash"
                    % suggestionId)
            if got != expectedHash:
                raise ValueError(
                    "建议 %s 的证据哈希不匹配（expected %s, got %s）"
                    % (suggestionId, expectedHash, got))
        payload = json.loads(row["payload_json"] or "{}")
        applied: Dict[str, Any] = {}
        if decision == "approved" and row["kind"] == "term":
            termId = _slugTermId(str(payload.get("name") or ""))
            if self._terms.term(termId, tenantId=tenant) is None:
                self._terms.register(
                    termId, "concept",
                    label=str(payload.get("name") or ""),
                    definition=str(payload.get("description") or ""),
                    aliases=[str(a) for a in (payload.get("synonyms") or [])],
                    tenantId=tenant)
            self._catalog.linkTableTerm(tenant, str(payload.get("table_id") or ""), termId)
            applied = {"term_id": termId,
                       "table_id": str(payload.get("table_id") or "")}
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "UPDATE ontology_schema_suggestions SET status = ?, reviewed_at = ?,"
                " reviewed_by = ? WHERE suggestion_id = ?",
                (decision, _now(), str(reviewedBy or ""), str(suggestionId or "")))
        result = dict(applied)
        result.update({"suggestion_id": str(suggestionId), "status": decision})
        return result

    # ── 内部 ────────────────────────────────────────────────

    def _hasActiveSuggestion(self, tenant: str, source: str, kind: str,
                             target: str) -> bool:
        """同目标已有任何状态的建议行即跳过：pending/approved 不重复生成，
        rejected 也不重生——人工否决是决定，不是噪声（机器不再纠缠）。"""
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT 1 FROM ontology_schema_suggestions"
                " WHERE tenant_id = ? AND source_id = ? AND kind = ? AND target = ?"
                " LIMIT 1",
                (tenant, source, kind, target)).fetchone()
        return row is not None

    def _recordSuggestion(self, tenant: str, source: str, kind: str, target: str,
                          payload: Dict[str, Any], basis: str,
                          confidence: float) -> str:
        suggestionId = "schsug_%s" % uuid.uuid4().hex[:12]
        payloadJson = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        evidenceHash = hashlib.sha256(payloadJson.encode("utf-8")).hexdigest()[:16]
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "INSERT OR IGNORE INTO ontology_schema_suggestions"
                " (suggestion_id, tenant_id, source_id, kind, target, payload_json,"
                "  basis, confidence, status, evidence_hash, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,'pending',?,?)",
                (suggestionId, tenant, source, kind, target, payloadJson,
                 basis, confidence, evidenceHash, _now()))
        return suggestionId

    def _termPayload(self, table: Dict[str, Any],
                     llmCall: Optional[Callable[[str], str]]) -> Dict[str, Any]:
        """术语建议载荷：确定性基线必得；llmCall 给了才精化，失败回退不吞。"""
        tableName = str(table["table_name"])
        columns = [dict(c) for c in (table.get("columns") or [])]
        columnNameList = [str(c["column_name"]) for c in columns]
        name = humanizeTableName(tableName)
        description = "表 %s 的业务概念，含 %d 列。" % (tableName, len(columns))
        synonyms: List[str] = []
        columnNames = {c: humanizeTableName(c) for c in columnNameList}
        basis = "rule"
        if llmCall is not None:
            try:
                raw = llmCall(_LLM_ENRICH_PROMPT.format(
                    table=tableName, columns=", ".join(columnNameList)))
                data = parseLlmJson(raw)
                if data and str(data.get("name") or "").strip():
                    name = str(data["name"]).strip()
                    description = str(data.get("description") or description).strip() \
                        or description
                    synonyms = [str(s) for s in (data.get("synonyms") or [])
                                if str(s).strip()][:8]
                    llmColumns = data.get("columns") or []
                    mapped = {}
                    for entry in llmColumns:
                        if not isinstance(entry, dict):
                            continue
                        key = str(entry.get("column") or "")
                        if key in columnNames and str(entry.get("display_name") or "").strip():
                            mapped[key] = str(entry["display_name"]).strip()
                    columnNames.update(mapped)
                    basis = "llm"
            except Exception:  # noqa: BLE001 - LLM 失败回退确定性基线，不产空建议
                basis = "rule"
        return {"table_id": str(table["catalog_table_id"]),
                "table_name": tableName,
                "name": name, "description": description, "synonyms": synonyms,
                "columns": [{"column": c, "display_name": d}
                            for c, d in columnNames.items()],
                "_basis": basis, "_confidence": 0.7 if basis == "llm" else 0.5}

    @staticmethod
    def _probeEdge(probeRunner: Callable[[str], List[Dict[str, Any]]],
                   edge: Dict[str, Any]) -> bool:
        """join 探针：两表按推断键连一行即证实（值域核对留给有采样的后续批）。"""
        sourceTable = str(edge.get("source_table") or "")
        sourceColumn = str(edge.get("source_column") or "")
        targetTable = str(edge.get("target_table") or "")
        targetColumn = str(edge.get("target_column") or "id")
        for ident in (sourceTable, sourceColumn, targetTable, targetColumn):
            if not _IDENTIFIER_RE.match(ident):
                return False
        sql = ("SELECT 1 AS hit FROM {st} s JOIN {tt} t"
               " ON CAST(s.{sc} AS TEXT) = CAST(t.{tc} AS TEXT) LIMIT 1").format(
            st=sourceTable, sc=sourceColumn, tt=targetTable, tc=targetColumn)
        try:
            rows = probeRunner(sql)
        except Exception:  # noqa: BLE001 - 探针失败＝未证实，不抬置信度
            return False
        return bool(rows)
