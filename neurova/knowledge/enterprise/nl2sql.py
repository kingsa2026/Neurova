# -*- coding: utf-8 -*-
"""NL2SQL 问数 grounding（对照研究 P1-4 批一，2026-11-15）＋查询历史回灌（P2-3）。

面向已连接企业源的「自然语言 → SQL → 执行 → 带 SQL 与步骤的答案」。批一范围
（报告 §6 P1-4 拆批约定）：目录 grounding + 确定性 join 路径 + 生成/校验/执行
+ 诚实拒答；修复环一轮；空结果如实报（值探针属后续批）。

纪律：
- **只读硬闸**：生成 SQL 过 `assertReadonlySelect`（写意图/多语句/注释拼接
  显式拒），表名必须全部在源目录白名单内，行数按方言强制收敛；
- **执行面**：只认适配器 `executeReadonly`（SQL 族可选能力）；无该能力的源
  只出计划不出行；
- **默认关**：端点层 env `NEUROVA_NL2SQL_ENABLED` 门控，本模块不读环境；
- **历史回灌（P2-3）**：每次问答落 `ontology_query_history`（诚实审计），
  高频表组合可建议为 sql_pattern 候选（走 P1-2 建议审批流，批准后进
  grounding 少样本，不自动执行任何东西）。
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Callable, Dict, List, Optional

from neurova.core.time_utils import nowIso as _now
from neurova.core.tenant_scope import tenant_sql_where

#: v53：问数历史（诚实审计：成功/失败/拒答都留行）。
_SCHEMA_V53_QUERY_HISTORY = """
CREATE TABLE IF NOT EXISTS ontology_query_history (
    query_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    source_id TEXT NOT NULL,
    question TEXT NOT NULL,
    sql_text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ok',
    row_count INTEGER NOT NULL DEFAULT 0,
    error_text TEXT NOT NULL DEFAULT '',
    asked_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_query_history_tenant
    ON ontology_query_history(tenant_id, source_id, created_at);
"""

_MAX_REPAIR_ROUNDS = 2
_MAX_ROWS = 200

#: P1-3 贡献度档位（确定性批一）：misleading 留名——确定性 grounding 下
#: 「误导」不可自证，待模型评估批再判。
ASSESSMENT_VERDICTS = ("essential", "helpful", "marginal", "not_assessed")


def _assessGrounding(sql: str, context: Optional[Dict[str, Any]],
                     attempts: int, lastError: str) -> Dict[str, Any]:
    """本体贡献度评估（P1-3，确定性规则版，零额外模型成本）。

    - essential：grounding 的术语映射/join 路径实际进入了最终 SQL（首轮即成）；
    - helpful：grounding 参与了修复（修复轮后成功）；
    - marginal：成功但 grounding 零命中（单表自明）。
    grounds 如实记录命中面，gaps 记录越界尝试。
    """
    context = context or {}
    usedTables = set(tablesInSql(sql))
    hintTables = {str(h.get("table") or "") for h in (context.get("termHints") or [])}
    # join 命中要求 SQL 真的做了连接（单表查询谈不上用了连接路径）
    hasJoin = re.search(r"\bjoin\b", str(sql or ""), re.IGNORECASE) is not None
    joinTables: set = set()
    for path in (context.get("joinPaths") or {}).values():
        for hop in path:
            joinTables.add(str(hop.get("source_table") or ""))
            joinTables.add(str(hop.get("target_table") or ""))
    grounds = {
        "terms": sorted(t for t in usedTables & hintTables if t),
        "joins": sorted(t for t in usedTables & joinTables if t) if hasJoin else [],
        "tables": sorted(t for t in usedTables if t),
        "patterns": sum(1 for p in (context.get("patterns") or [])
                        if set(tablesInSql(str(p.get("sql") or ""))) & usedTables),
    }
    gaps: List[str] = []
    if attempts > 1:
        verdict = "helpful"
        if "目录外表" in str(lastError or ""):
            gaps.append("out_of_catalog_attempt")
    elif grounds["terms"] or grounds["joins"]:
        verdict = "essential"
    else:
        verdict = "marginal"
    return {"verdict": verdict, "grounds": grounds, "gaps": gaps}


def _refusalGaps(reason: str) -> List[str]:
    """拒因 → 缺口归类（诚实拒答也要说清缺什么）。"""
    gaps: List[str] = []
    text = str(reason or "")
    if "源目录为空" in text:
        gaps.append("missing_catalog")
    if "未配置可用 LLM" in text:
        gaps.append("missing_model")
    if "连续" in text and "轮" in text:
        gaps.append("invalid_sql")
        if "目录外表" in text:
            gaps.append("out_of_catalog_attempt")
    return gaps or ["missing_term"]


def _buildCitations(sql: str, context: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    """答案的逐论断引用（P3-1c，血缘差距三）：每个论断可溯到四型来源——

    catalog_table（目录表）/ term（审批回填的术语映射）/ join_path（已核实的
    连接边）/ approved_pattern（已批准历史模式）。SQL 引用的表全部在目录
    白名单内（只读硬闸保证），因此可答结果的 citations 恒非空。
    """
    context = context or {}
    usedTables = sorted({t for t in tablesInSql(sql) if t})
    hintByTable = {str(h.get("table") or ""): str(h.get("term_id") or "")
                   for h in (context.get("termHints") or [])}
    hasJoin = re.search(r"\bjoin\b", str(sql or ""), re.IGNORECASE) is not None
    citations: List[Dict[str, str]] = [{"kind": "catalog_table", "ref": t}
                                       for t in usedTables]
    for table in usedTables:
        termId = hintByTable.get(table) or ""
        if termId:
            citations.append({"kind": "term", "ref": termId})
    if not hasJoin:
        return citations
    joinTables = set(usedTables)
    for target, hops in (context.get("joinPaths") or {}).items():
        if str(target) not in joinTables:
            continue
        for hop in hops:
            ref = "%s.%s=%s.%s" % (hop.get("source_table"),
                                   hop.get("source_column"),
                                   hop.get("target_table"),
                                   hop.get("target_column") or "id")
            citation = {"kind": "join_path", "ref": ref}
            if citation not in citations:
                citations.append(citation)
    for pattern in (context.get("patterns") or []):
        if set(tablesInSql(str(pattern.get("sql") or ""))) & joinTables:
            citations.append({"kind": "approved_pattern",
                              "ref": str(pattern.get("question") or "")[:80]})
    return citations

_LLM_SQL_PROMPT = """你是严谨的数据分析 SQL 编写器。只依据给出的目录与连接提示写一条只读 SELECT。

可用表（table_name(列: 类型)）：
{tables}

已核实的连接路径（按顺序 JOIN，不得跳表）：
{joins}

业务词映射（术语 → 表）：
{termHints}

历史参考模式（同源已批准的问法→SQL，只借鉴结构，不抄字面）：
{patterns}

规则：
- 只输出一条 SELECT/WITH 只读查询；禁止 INSERT/UPDATE/DELETE/DDL/PRAGMA 等；
- 表名必须与「可用表」逐字一致；过滤值只能来自问题本身；
- 必须带行数上限（LIMIT/FETCH FIRST），不超过 {maxRows}；
- 若目录确实覆盖不了问题，输出 {{"unanswerable": true, "reason": "..."}}。

输出严格 JSON（不要解释之外的多余文本）：
{{"sql": "SELECT ...", "explanation": "一句话说明", "unanswerable": false, "reason": ""}}

问题：{question}"""

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)
_FROM_TABLE_RE = re.compile(
    r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?)",
    re.IGNORECASE)


def parseLlmSql(text: str) -> Optional[Dict[str, Any]]:
    """LLM 输出 → {sql, explanation, unanswerable, reason}；不可信输入 → None。"""
    if not text:
        return None
    match = _FENCE_RE.search(text)
    raw = match.group(1) if match else text
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except Exception:  # noqa: BLE001 - LLM 输出不可信
        return None
    return data if isinstance(data, dict) else None


def planJoinPaths(edges: List[Dict[str, Any]],
                  startTable: str) -> Dict[str, List[Dict[str, Any]]]:
    """从锚表出发的 BFS 最短连接路径（确定性，无 LLM）。

    边无向（外键两侧都可走）；返回 {目标表: [hop, ...]}，hop 含
    source_table/source_column/target_table/target_column。锚表自身与
    不可达表不在结果里。
    """
    adjacency: Dict[str, List[Dict[str, Any]]] = {}
    for edge in edges:
        a = str(edge.get("source_table") or "")
        b = str(edge.get("target_table") or "")
        if not a or not b:
            continue
        adjacency.setdefault(a, []).append(edge)
        adjacency.setdefault(b, []).append({**edge,
                                            "source_table": b, "source_column": edge.get("target_column", ""),
                                            "target_table": a, "target_column": edge.get("source_column", "")})
    start = str(startTable or "")
    if start not in adjacency:
        return {}
    paths: Dict[str, List[Dict[str, Any]]] = {}
    visited = {start}
    frontier: List[List[Dict[str, Any]]] = [[]]
    while frontier:
        nextFrontier: List[List[Dict[str, Any]]] = []
        for path in frontier:
            currentNode = start if not path else path[-1]["target_table"]
            for edge in adjacency.get(currentNode, []):
                target = str(edge.get("target_table") or "")
                if target in visited or target == currentNode:
                    continue
                visited.add(target)
                extended = path + [edge]
                paths[target] = extended
                nextFrontier.append(extended)
        frontier = nextFrontier
    return paths


def tablesInSql(sql: str) -> List[str]:
    """粗提 FROM/JOIN 目标表名（白名单校验用；列级校验靠执行期诚实报错）。"""
    return [m.group(1) for m in _FROM_TABLE_RE.finditer(str(sql or ""))]


class Nl2SqlService:
    """问数编排：grounding → 生成 → 校验（含一轮修复）→ 执行 → 历史落账。"""

    def __init__(self, store: Any) -> None:
        self._store = store
        from ..foundation.foundation_schema import applyTo

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    # ── 主流程 ──────────────────────────────────────────────

    def answerQuestion(self, tenantId: str, sourceId: str, question: str,
                       llmCall: Optional[Callable[[str], str]],
                       executor: Optional[Callable[[str, int], List[Dict[str, Any]]]],
                       askedBy: str = "", execute: bool = True,
                       maxRows: int = _MAX_ROWS) -> Dict[str, Any]:
        """一次问答。executor=适配器 executeReadonly 的同步桥（None＝只出计划）。

        返回 {answerable, sql, explanation, rows, row_count, truncated, steps,
        status}；不可答/校验失败如实拒答，历史表逐次落行（P2-3 审计）。
        """
        tenant = str(tenantId or "default")
        source = str(sourceId or "")
        question = str(question or "").strip()
        steps: List[str] = []
        maxRows = max(1, min(int(maxRows), _MAX_ROWS))

        context = self._groundingContext(tenant, source, question)
        if context is None:
            return self._refuse(tenant, source, question, askedBy,
                                "源目录为空——请先刷新 schema 目录", steps)
        steps.append("grounding：候选表 %s" % (context["scores"][:3] or "无"))

        if not llmCall:
            return self._refuse(tenant, source, question, askedBy,
                                "未配置可用 LLM，无法生成 SQL", steps)

        attempts = 0
        lastError = ""
        while attempts <= _MAX_REPAIR_ROUNDS:
            attempts += 1
            prompt = self._buildPrompt(context, question, maxRows,
                                       repairError=lastError)
            raw = llmCall(prompt)
            data = parseLlmSql(raw)
            if data is None:
                lastError = "输出不是可解析的 JSON"
                steps.append("attempt %d：%s" % (attempts, lastError))
                continue
            if data.get("unanswerable"):
                reason = str(data.get("reason") or "目录覆盖不了该问题")
                return self._refuse(tenant, source, question, askedBy,
                                    reason, steps, explanation=str(data.get("explanation") or ""))
            sql = str(data.get("sql") or "").strip()
            explanation = str(data.get("explanation") or "").strip()
            try:
                self._validateSql(sql, context["tables"], maxRows)
            except ValueError as exc:
                lastError = str(exc)
                steps.append("attempt %d 校验拒：%s" % (attempts, lastError))
                continue
            steps.append("SQL 通过只读校验（attempt %d）" % attempts)
            rows: List[Dict[str, Any]] = []
            truncated = False
            executionError = ""
            if execute and executor is not None:
                try:
                    rows = executor(sql, maxRows) or []
                    truncated = len(rows) >= maxRows
                    steps.append("执行返回 %d 行" % len(rows))
                except Exception as exc:  # noqa: BLE001 - 执行失败如实回传，不吞
                    executionError = "%s: %s" % (type(exc).__name__, exc)
                    steps.append("执行失败：%s" % executionError)
                    lastError = executionError
                    continue
            elif execute and executor is None:
                steps.append("该源不支持只读执行，仅返回计划")
            status = "ok" if not executionError else "error"
            result = {"answerable": True, "sql": sql, "explanation": explanation,
                      "rows": rows, "row_count": len(rows), "truncated": truncated,
                      "steps": steps, "status": status,
                      "assessment": _assessGrounding(sql, context, attempts,
                                                     lastError),
                      # 逐论断引用（P3-1c）：可答结果必可溯到目录/术语/连接边
                      "citations": _buildCitations(sql, context)}
            if executionError:
                result["error"] = executionError
            self._recordHistory(tenant, source, question, sql, status,
                                len(rows), executionError, askedBy)
            return result
        return self._refuse(tenant, source, question, askedBy,
                            "连续 %d 轮未能产出合法只读 SQL（最后错误：%s）"
                            % (_MAX_REPAIR_ROUNDS + 1, lastError), steps)

    # ── grounding ───────────────────────────────────────────

    def _groundingContext(self, tenant: str, source: str,
                          question: str) -> Optional[Dict[str, Any]]:
        """目录 + 术语链接 + 外键边 + 已批准模式 → 生成上下文。目录空即 None。"""
        from .schema_catalog import SchemaCatalogStore

        catalog = SchemaCatalogStore(self._store)
        tables = catalog.listTables(tenant, sourceId=source, limit=10000)
        if not tables:
            return None
        details: Dict[str, Dict[str, Any]] = {}
        for table in tables:
            detail = catalog.tableDetail(tenant, str(table["catalog_table_id"])) or {}
            details[str(table["table_name"])] = detail
        edges = catalog.foreignKeyEdges(tenant, sourceId=source)
        termHints = self._termHints(tenant, details)
        patterns = self._approvedPatterns(tenant, source)
        scores = self._scoreTables(question, details, termHints)
        anchor = scores[0][0] if scores else ""
        joinPaths = planJoinPaths(edges, anchor) if anchor else {}
        return {"tables": details, "edges": edges, "termHints": termHints,
                "patterns": patterns, "scores": scores, "anchor": anchor,
                "joinPaths": joinPaths}

    def _termHints(self, tenant: str,
                   details: Dict[str, Dict[str, Any]]) -> List[Dict[str, str]]:
        """目录表上经 P1-2 审批回填的 term_id → 术语标签（grounding 的业务词映射）。"""
        from ..ontology.term_registry import OntologyTermRegistry

        registry = OntologyTermRegistry(self._store)
        hints: List[Dict[str, str]] = []
        for tableName, detail in details.items():
            termId = str((detail or {}).get("term_id") or "")
            if not termId:
                continue
            term = registry.term(termId, tenantId=tenant)
            if term is None:
                continue
            hints.append({"table": tableName, "term_id": termId,
                          "term_label": str(term.get("label") or termId)})
        return hints

    def _approvedPatterns(self, tenant: str, source: str) -> List[Dict[str, Any]]:
        with self._store._lock:
            tenantClause, tenantParams = tenant_sql_where(tenant)
            rows = self._store._conn.execute(
                "SELECT payload_json FROM ontology_schema_suggestions"
                " WHERE %s AND source_id = ? AND kind = 'sql_pattern'"
                " AND status = 'approved' ORDER BY reviewed_at LIMIT 5" % tenantClause,
                (*tenantParams, source)).fetchall()
        return [json.loads(r["payload_json"] or "{}") for r in rows]

    @staticmethod
    def _scoreTables(question: str, details: Dict[str, Dict[str, Any]],
                     termHints: List[Dict[str, str]]) -> List[tuple]:
        tokens = [t for t in re.split(r"[\W_]+", str(question or "").lower()) if t]
        cjkRuns = re.findall(r"[\u4e00-\u9fff]{2,}", str(question or ""))
        scores: List[tuple] = []
        for tableName, detail in details.items():
            haystackParts = [tableName.lower()]
            for column in detail.get("columns") or []:
                haystackParts.append(str(column.get("column_name") or "").lower())
            for hint in termHints:
                if hint.get("table") == tableName:
                    haystackParts.append(str(hint.get("term_label") or "").lower())
            haystack = " ".join(p for p in haystackParts if p)
            score = sum(1 for token in tokens if token and token in haystack)
            score += sum(2 for run in cjkRuns if run and run in haystack)
            if score > 0:
                scores.append((tableName, score))
        scores.sort(key=lambda pair: (-pair[1], pair[0]))
        return scores

    def _buildPrompt(self, context: Dict[str, Any], question: str,
                     maxRows: int, repairError: str = "") -> str:
        tableLines = []
        for tableName, detail in context["tables"].items():
            columns = ", ".join(
                "%s: %s" % (c.get("column_name"), c.get("data_type") or "?")
                for c in (detail.get("columns") or []))
            tableLines.append("%s(%s)" % (tableName, columns))
        pathLines = []
        for target, hops in list(context["joinPaths"].items())[:6]:
            pathLines.append("→ ".join(
                "%s.%s=%s.%s" % (h["source_table"], h["source_column"],
                                 h["target_table"], h["target_column"] or "id")
                for h in hops) + " （到 %s）" % target)
        patternLines = ["%s ⇒ %s" % (p.get("question"), p.get("sql"))
                        for p in context["patterns"] if p.get("sql")]
        repairNote = ("\n上一轮错误（必须修正）：%s" % repairError) if repairError else ""
        return _LLM_SQL_PROMPT.format(
            tables="\n".join(tableLines), joins="\n".join(pathLines) or "（无——单表查询）",
            termHints="\n".join("%s → %s" % (h["term_label"], h["table"])
                                for h in context["termHints"]) or "（无已批准映射）",
            patterns="\n".join(patternLines) or "（无）",
            maxRows=maxRows, question=question) + repairNote

    # ── 校验 ────────────────────────────────────────────────

    @staticmethod
    def _validateSql(sql: str, tables: Dict[str, Any], maxRows: int) -> None:
        from .connectors_sql import assertReadonlySelect

        checked = assertReadonlySelect(sql)  # 只读硬闸（写意图/多语句/注释）
        referenced = tablesInSql(checked)
        unknown = [t for t in referenced if t not in tables]
        if unknown:
            raise ValueError("SQL 引用了目录外表: %s" % ", ".join(sorted(set(unknown))))
        if not referenced:
            raise ValueError("SQL 未引用任何目录表")
        if maxRows and not re.search(r"\bLIMIT\s+\d+\b|\bFETCH\s+FIRST\b|\bTOP\s*\(",
                                     checked, re.IGNORECASE):
            raise ValueError("生成 SQL 必须自带行数上限（LIMIT/FETCH FIRST/TOP）")

    # ── 历史与回灌（P2-3）───────────────────────────────────

    def _recordHistory(self, tenant: str, source: str, question: str, sql: str,
                       status: str, rowCount: int, errorText: str,
                       askedBy: str) -> str:
        queryId = "nlq_%s" % uuid.uuid4().hex[:12]
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "INSERT INTO ontology_query_history"
                " (query_id, tenant_id, source_id, question, sql_text, status,"
                "  row_count, error_text, asked_by, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (queryId, tenant, source, question, sql, status,
                 int(rowCount), str(errorText or ""), str(askedBy or ""), _now()))
        return queryId

    def listHistory(self, tenantId: str, sourceId: str,
                    limit: int = 50) -> List[Dict[str, Any]]:
        with self._store._lock:
            tenantClause, tenantParams = tenant_sql_where(str(tenantId or "default"))
            rows = self._store._conn.execute(
                "SELECT * FROM ontology_query_history"
                " WHERE %s AND source_id = ?"
                " ORDER BY created_at DESC, query_id LIMIT ?" % tenantClause,
                (*tenantParams, str(sourceId or ""),
                 max(1, int(limit)))).fetchall()
        return [dict(r) for r in rows]

    def suggestPatternsFromHistory(self, tenantId: str, sourceId: str,
                                   topN: int = 3) -> Dict[str, Any]:
        """历史 → sql_pattern 候选（P2-3）：按涉及表组合频次取 topN，
        走 P1-2 建议审批流（pending），批准后进 grounding 少样本。"""
        from ..ontology.schema_suggester import SchemaSuggester

        tenant = str(tenantId or "default")
        source = str(sourceId or "")
        with self._store._lock:
            tenantClause, tenantParams = tenant_sql_where(tenant)
            rows = self._store._conn.execute(
                "SELECT question, sql_text FROM ontology_query_history"
                " WHERE %s AND source_id = ? AND status = 'ok'"
                " ORDER BY created_at DESC LIMIT 200" % tenantClause,
                (*tenantParams, source)).fetchall()
        grouped: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            sql = str(row["sql_text"] or "")
            tablesKey = "|".join(sorted(set(tablesInSql(sql))))
            if not tablesKey:
                continue
            entry = grouped.setdefault(tablesKey, {
                "count": 0, "question": str(row["question"] or ""),
                "sql": sql, "tables": tablesKey})
            entry["count"] += 1
        suggester = SchemaSuggester(self._store)
        created = 0
        for key in sorted(grouped, key=lambda k: -grouped[k]["count"])[:max(1, int(topN))]:
            entry = grouped[key]
            target = "sql_pattern:%s:%s" % (source, key)
            if suggester._hasActiveSuggestion(tenant, source, "sql_pattern", target):
                continue
            suggester._recordSuggestion(
                tenant, source, "sql_pattern", target,
                {"question": entry["question"], "sql": entry["sql"],
                 "tables": entry["tables"], "usage_count": entry["count"]},
                basis="rule", confidence=min(0.9, 0.4 + 0.1 * entry["count"]))
            created += 1
        return {"patterns_suggested": created,
                "history_rows_considered": len(rows)}

    # ── 内部 ────────────────────────────────────────────────

    def _refuse(self, tenant: str, source: str, question: str, askedBy: str,
                reason: str, steps: List[str],
                explanation: str = "") -> Dict[str, Any]:
        self._recordHistory(tenant, source, question, "", "refused", 0, reason,
                            askedBy)
        return {"answerable": False, "sql": "", "explanation": explanation,
                "rows": [], "row_count": 0, "truncated": False,
                "steps": steps, "status": "refused", "reason": reason,
                # 拒答不硬评分（本体没参与生成）：verdict 如实标 not_assessed，
                # gaps 按拒因归类——缺目录/缺模型/缺术语/非法 SQL。
                "assessment": {"verdict": "not_assessed",
                               "grounds": {"terms": [], "joins": [],
                                           "tables": [], "patterns": 0},
                               "gaps": _refusalGaps(reason)},
                # 没有产出就没有可引用的论断（P3-1c）
                "citations": []}
