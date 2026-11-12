"""Simulation 克隆世界推演（specs/2026-11-12 §7 W5）。

先演后决的最小形态：生产库经 stdlib `sqlite3` backup API 复制到**临时副本**，
假设（候选断言/状态迁移/动作效果）在副本内经**同一咽喉**注入——dispatch 自动
点燃规则与函数引擎（零引擎改造）；前后快照 diff 出新增/撤销派生事实、状态变化、
受影响主体集。**副本只读生产、零生产写**（唯一例外＝ontology_simulations 台账
追加一行，v46——先演后决审计互链的台账本体）。

规模边界：scope 事实行数超 `SCOPE_FACT_CAP` 显式拒 `ScopeTooLargeError`
（不静默截断）。副本临时文件 run 结束即删（TTL 哨兵测试钉住）。
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
import tempfile
import uuid
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: scope 事实行数上限（超限显式拒，不静默截断——与 D1 同款诚实形态）
SCOPE_FACT_CAP = 5000

_SCHEMA_V46_SIMULATIONS = """
CREATE TABLE IF NOT EXISTS ontology_simulations (
    simulation_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    agent_id TEXT NOT NULL DEFAULT 'default',
    scope_json TEXT NOT NULL DEFAULT '{}',
    hypothesis_json TEXT NOT NULL DEFAULT '[]',
    diff_summary_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class ScopeTooLargeError(ValueError):
    """scope 事实行数超上限——显式拒（不静默截断）。"""


def _snapshot(store: Any, agentId: str, tenantId: str) -> Dict[str, Dict[str, Any]]:
    """(agent, tenant) 域内事实快照：fact_id → 行（diff 的比较基线）。"""
    with store._lock:
        rows = store._conn.execute(
            "SELECT fact_id, subject_key, predicate_term_id, object_term, status,"
            " qualifier_json FROM knowledge_facts"
            " WHERE agent_id = ? AND tenant_id = ?"
            " ORDER BY fact_id", (agentId, tenantId)).fetchall()
    return {str(r["fact_id"]): {
        "fact_id": str(r["fact_id"]),
        "subject_key": str(r["subject_key"]),
        "predicate_term_id": str(r["predicate_term_id"]),
        "object_term": str(r["object_term"]),
        "status": str(r["status"]),
        "qualifier": json.loads(r["qualifier_json"] or "{}"),
    } for r in rows}


def _labelOf(store: Any, subjectKey: str) -> str:
    row = None
    with store._lock:
        row = store._conn.execute(
            "SELECT canonical_label FROM knowledge_subjects WHERE subject_key = ?",
            (subjectKey,)).fetchone()
    return str(row["canonical_label"]) if row is not None else subjectKey


def _appendLedger(store: Any, tenantId: str, agentId: str, scope: Dict[str, Any],
                  hypotheses: Dict[str, Any], diff: Dict[str, Any]) -> str:
    """台账只追加一行（v46）——先演后决审计互链的台账本体（唯一生产写）。"""
    simulationId = "sim_%s" % uuid.uuid4().hex[:12]
    with store._lock, store._conn:
        store._conn.execute(
            "INSERT INTO ontology_simulations"
            " (simulation_id, tenant_id, agent_id, scope_json, hypothesis_json,"
            "  diff_summary_json, created_at) VALUES (?,?,?,?,?,?,?)",
            (simulationId, str(tenantId or "default"), str(agentId or "default"),
             json.dumps(scope, ensure_ascii=False),
             json.dumps(hypotheses, ensure_ascii=False),
             json.dumps(diff, ensure_ascii=False), _now()))
    return simulationId


def _injectHypotheses(copyStore: Any, hypotheses: Dict[str, Any],
                      agentId: str, tenantId: str) -> List[str]:
    """假设在副本内经同一咽喉注入（dispatch 自动点燃规则＋函数引擎）。"""
    from ..foundation.admission import AdmissionRequest, productionAdmissionGate

    gate = productionAdmissionGate(copyStore, toolVersion="ontology_simulate")
    factIds: List[str] = []
    for spec in hypotheses.get("facts") or []:
        subject = str((spec or {}).get("subjectLabel") or "").strip()
        predicate = str((spec or {}).get("predicateTermId") or "").strip()
        obj = str((spec or {}).get("objectTerm") or "").strip()
        if not subject or not predicate or not obj:
            continue  # 形状不完整的假设条目如实跳过（不入副本）
        content = "%s %s %s" % (subject, predicate, obj)
        try:
            receipt = gate.admit(AdmissionRequest(
                agentId=agentId, tenantId=tenantId,
                subjectLabel=subject, predicateTermId=predicate,
                objectTerm=obj, content=content,
                assertions=[{"actorType": "pipeline", "actorId": "ontology_simulate",
                             "mediumRef": "simulate", "statementText": content}],
                activityKind="admit",
                activityBasis="simulation._injectHypotheses（副本假设注入）"))
            factIds.append(receipt.factId)
        except ValueError as exc:
            logger.warning("simulation: 假设注入被拒（%s %s %s）: %s",
                           subject, predicate, obj, exc)
    return factIds


def runSimulation(store: Any, scope: Dict[str, Any], hypotheses: Dict[str, Any],
                  workDir: Optional[str] = None,
                  simulationId: Optional[str] = None) -> Dict[str, Any]:
    """克隆世界推演：备份→副本注入→引擎到不动点→diff→台账追加→副本即删。

    返回 {simulation_id, diff:{added,removed,affected_subjects}, scoped_facts}。
    生产库唯一写＝台账追加一行；其余全部发生在副本内。"""
    from ..foundation.foundation_schema import applyTo

    with store._lock, store._conn:
        applyTo(store._conn)  # v46 台账表随迁移链装配（副本库亦然）
    agentId = str((scope or {}).get("agentId") or "default")
    tenantId = str((scope or {}).get("tenantId") or "default")
    hypotheses = hypotheses or {}

    # 规模边界：scope 事实行数（agent+tenant 域）超上限显式拒
    with store._lock:
        n = store._conn.execute(
            "SELECT COUNT(*) AS n FROM knowledge_facts"
            " WHERE agent_id = ? AND tenant_id = ?",
            (agentId, tenantId)).fetchone()["n"]
    if int(n) > SCOPE_FACT_CAP:
        raise ScopeTooLargeError(
            "scope 过大：%d 行事实超上限 %d（推演只收 ≤%d 行的域，不静默截断）"
            % (int(n), SCOPE_FACT_CAP, SCOPE_FACT_CAP))

    baseline = _snapshot(store, agentId, tenantId)
    workDirCreated = False
    if workDir is None:
        workDir = tempfile.mkdtemp(prefix="kb_sim_")
        workDirCreated = True
    baseName = os.path.basename(str(getattr(store, "_db_path", "") or "kb"))
    copyPath = os.path.join(workDir, "%s-sim-%s.db" % (baseName, uuid.uuid4().hex[:8]))
    try:
        # stdlib backup API：生产库整库复制到临时副本（隔离的根——副本零回写）
        with store._lock:
            store._conn.commit()
        copyConn = sqlite3.connect(copyPath)
        try:
            store._conn.backup(copyConn)
        finally:
            copyConn.close()

        from ..foundation.knowledge_facts import KnowledgeFactStore

        copyStore = KnowledgeFactStore(copyPath)
        try:
            _injectHypotheses(copyStore, hypotheses, agentId, tenantId)
            # 引擎到不动点（规则＋函数——与生产同一批装配形状，零改造；
            # 副本推导事实同样必须过副本咽喉，gateFactory 与生产同款）
            from ..foundation.admission import productionAdmissionGate as _gate
            from .function_engine import FunctionEngine
            from .rule_engine import ForwardChainingEngine

            copyGate = lambda st: _gate(st, toolVersion="ontology_simulate")  # noqa: E731
            ForwardChainingEngine(copyStore, gateFactory=copyGate).fireAll(
                agentId=agentId, tenantId=tenantId)
            functions = FunctionEngine(copyStore)
            for fn in _functionRegistryOf(copyStore).list(tenantId=tenantId):
                for pred in (fn.get("scope") or {}).get("depends_on", []):
                    functions.fireFor(agentId, pred, tenantId=tenantId)
            after = _snapshot(copyStore, agentId, tenantId)
        finally:
            copyStore.close()
    finally:
        try:
            if os.path.exists(copyPath):
                os.remove(copyPath)
            if workDirCreated and os.path.isdir(workDir) and not os.listdir(workDir):
                os.rmdir(workDir)
        except OSError as exc:  # noqa: BLE001 - 清理失败留名（哨兵测试会抓到残留）
            logger.warning("simulation: 副本清理失败 %s: %s", copyPath, exc)

    added = [after[fid] for fid in after.keys() if fid not in baseline]
    removed = [baseline[fid] for fid in baseline.keys() if fid not in after]
    affectedSubjects = sorted({_labelOf(store, f["subject_key"]) for f in added})
    diff = {"added": added, "removed": removed,
            "affected_subjects": affectedSubjects,
            "state_changes": [f for f in added
                              if f["predicate_term_id"] == "has_state"]}
    simulationId = _appendLedger(store, tenantId, agentId, scope, hypotheses,
                                 {"added_count": len(added),
                                  "removed_count": len(removed),
                                  "affected_subjects": affectedSubjects})
    return {"simulation_id": simulationId, "diff": diff,
            "scoped_facts": len(baseline)}


def _functionRegistryOf(store: Any):
    from .function_registry import FunctionRegistry

    return FunctionRegistry(store)
