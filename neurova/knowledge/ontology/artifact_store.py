# -*- coding: utf-8 -*-
"""工件级内容地址不可变存储（specs/2026-11-12 §18 C1/C2 共享契约）。

- **内容寻址**：主键＝SHA-256(content)——同内容幂等零二次写，异内容必异键；
- **write-once**：行只插不改不删；同键重放校验内容一致（哈希即内容，防御性双查）；
- **消费面**：C1 RDF/XML 导入原始字节、C2 领域包工件的不可变版本＋校验和＋归属；
  事实级 lineage（digest 链）仍是溯源单源，本面只管**工件层**。
- 表随 foundation_schema v50 步就绪（ontology_artifacts）。
"""

from __future__ import annotations

import datetime
import hashlib
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 工件种类闭集（新种类在登记处加，消费面按 kind 分流）
ARTIFACT_KINDS = ("rdf_import", "domain_pack", "external_ontology")

#: v50：工件级内容地址存储（specs/2026-11-12 §18 C1/C2）——
#:      主键＝SHA-256(content)，write-once（只插不改不删）
_SCHEMA_V50_ARTIFACTS = """
CREATE TABLE IF NOT EXISTS ontology_artifacts (
    artifact_sha256 TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    source_ref TEXT NOT NULL DEFAULT '',
    tenant_id TEXT NOT NULL DEFAULT 'default',
    agent_id TEXT NOT NULL DEFAULT '',
    content BLOB NOT NULL,
    registered_at TEXT NOT NULL
);
"""


def sha256Of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def putArtifact(store: Any, kind: str, content: bytes, sourceRef: str = "",
                tenantId: str = "default", agentId: str = "",
                registeredAt: Optional[str] = None) -> Dict[str, Any]:
    """写入工件（write-once）：返回 {sha256, created}。

    同 (sha256) 已存在时校验存储内容一致后幂等返回（created=False）——
    不可能同键异内容（键即哈希），防御性比对防存储层损坏被静默吞掉。
    kind 不在闭集 → ValueError。
    """
    if kind not in ARTIFACT_KINDS:
        raise ValueError("未知工件种类 %r（闭集：%s）" % (kind, ", ".join(ARTIFACT_KINDS)))
    digest = sha256Of(content)
    now = registeredAt or datetime.datetime.now(datetime.timezone.utc).isoformat()
    with store._lock, store._conn:
        existing = store._conn.execute(
            "SELECT content FROM ontology_artifacts WHERE artifact_sha256 = ?",
            (digest,)).fetchone()
        if existing is not None:
            stored = bytes(existing["content"])
            if stored != content:
                raise ValueError(
                    "工件 %s 存储内容与哈希不一致（存储层损坏——显式报错不静默）" % digest[:16])
            return {"sha256": digest, "created": False}
        store._conn.execute(
            "INSERT INTO ontology_artifacts"
            " (artifact_sha256, kind, source_ref, tenant_id, agent_id, content, registered_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (digest, kind, sourceRef, tenantId, agentId, content, now))
    return {"sha256": digest, "created": True}


def getArtifact(store: Any, sha256: str) -> Optional[bytes]:
    """按哈希读工件原始字节；未登记 → None。读时校验内容哈希（防静默损坏）。"""
    with store._lock:
        row = store._conn.execute(
            "SELECT content FROM ontology_artifacts WHERE artifact_sha256 = ?",
            (sha256,)).fetchone()
    if row is None:
        return None
    content = bytes(row["content"])
    actual = sha256Of(content)
    if actual != sha256:
        raise ValueError(
            "工件 %s 读出内容哈希 %s 不一致（不可变面被破坏——显式报错）" % (sha256[:16], actual[:16]))
    return content


def verifyArtifact(store: Any, sha256: str) -> Dict[str, Any]:
    """完整性核验：missing / ok / drift（存储内容哈希≠登记键）。"""
    with store._lock:
        row = store._conn.execute(
            "SELECT content FROM ontology_artifacts WHERE artifact_sha256 = ?",
            (sha256,)).fetchone()
    if row is None:
        return {"sha256": sha256, "status": "missing"}
    content = bytes(row["content"])
    actual = sha256Of(content)
    return {"sha256": sha256,
            "status": "ok" if actual == sha256 else "drift",
            "actual_sha256": actual}


def latestArtifact(store: Any, kind: str, tenantId: str = "default",
                   agentId: str = "") -> Optional[Dict[str, Any]]:
    """最近一次登记的某类工件（含字节）——C1 字节往返的读数单源。"""
    sql = ("SELECT artifact_sha256, kind, source_ref, tenant_id, agent_id, content,"
           " registered_at FROM ontology_artifacts WHERE kind = ? AND tenant_id = ?")
    params: List[Any] = [kind, tenantId]
    if agentId:
        sql += " AND agent_id = ?"
        params.append(agentId)
    sql += " ORDER BY registered_at DESC, artifact_sha256 LIMIT 1"
    with store._lock:
        row = store._conn.execute(sql, params).fetchone()
    if row is None:
        return None
    return {"sha256": row["artifact_sha256"], "kind": row["kind"],
            "source_ref": row["source_ref"], "tenant_id": row["tenant_id"],
            "agent_id": row["agent_id"], "content": bytes(row["content"]),
            "registered_at": row["registered_at"]}


def listArtifacts(store: Any, kind: Optional[str] = None,
                  tenantId: str = "default", limit: int = 100) -> List[Dict[str, Any]]:
    """工件清单（不含字节，只含元数据＋哈希——读面按哈希引用）。"""
    sql = ("SELECT artifact_sha256, kind, source_ref, tenant_id, agent_id, registered_at,"
           " LENGTH(content) AS byte_count FROM ontology_artifacts WHERE tenant_id = ?")
    params: List[Any] = [tenantId]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY registered_at DESC, artifact_sha256 LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    with store._lock:
        rows = store._conn.execute(sql, params).fetchall()
    return [{"sha256": r["artifact_sha256"], "kind": r["kind"], "source_ref": r["source_ref"],
             "tenant_id": r["tenant_id"], "agent_id": r["agent_id"],
             "registered_at": r["registered_at"], "byte_count": r["byte_count"]}
            for r in rows]
