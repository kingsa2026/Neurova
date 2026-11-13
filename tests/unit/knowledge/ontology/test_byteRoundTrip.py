# -*- coding: utf-8 -*-
"""C1 字节级无损往返（specs/2026-11-12 §18）：导入原始字节入工件存储＋按哈希读回
逐字节相等＋导出头单源（latest rdf_import 工件）＋v50 表就绪。

红：导入原始字节未入不可变存储 / 读回不一致 / 导出头读不到导入哈希。
绿：put→latest→get 全链逐字节一致；v50 表存在。
"""

from __future__ import annotations

import hashlib

from neurova.knowledge.foundation.foundation_schema import applyTo
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.artifact_store import (
    getArtifact,
    latestArtifact,
    putArtifact,
)
from neurova.knowledge.ontology.rdf_import import importRdfXml

_MINIMAL_RDF = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
    ' xmlns:ex="http://example.org/">'
    '<rdf:Description rdf:about="http://example.org/s1">'
    '<ex:p1>o1</ex:p1>'
    '</rdf:Description>'
    '</rdf:RDF>'
).encode("utf-8")


class TestByteRoundTrip:
    def test_importBytesIntoArtifactStore(self, tmp_path):
        store = KnowledgeFactStore(str(tmp_path / "kb.db"))
        try:
            result = importRdfXml(_MINIMAL_RDF)
            assert result.triple_count == 1
            rec = putArtifact(store, "rdf_import", result.original_bytes,
                              sourceRef="import-rdf", agentId="default")
            # 按哈希读回：逐字节相等（无损往返的硬判据）
            assert getArtifact(store, rec["sha256"]) == _MINIMAL_RDF
            assert rec["sha256"] == hashlib.sha256(_MINIMAL_RDF).hexdigest()
        finally:
            store.close()

    def test_exportHeaderSingleSource(self, tmp_path):
        """导出响应头引用的导入 SHA-256 单源＝latest rdf_import 工件（env 假源已退役）。"""
        store = KnowledgeFactStore(str(tmp_path / "kb.db"))
        try:
            assert latestArtifact(store, "rdf_import") is None, "未导入时诚实 None"
            result = importRdfXml(_MINIMAL_RDF)
            rec = putArtifact(store, "rdf_import", result.original_bytes, sourceRef="import-rdf")
            latest = latestArtifact(store, "rdf_import")
            assert latest is not None
            assert latest["sha256"] == rec["sha256"]
            assert latest["content"] == _MINIMAL_RDF
        finally:
            store.close()

    def test_v50ArtifactsTableExists(self, tmp_path):
        store = KnowledgeFactStore(str(tmp_path / "kb.db"))
        try:
            applyTo(store._conn)
            with store._lock:
                row = store._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                    " AND name='ontology_artifacts'").fetchone()
            assert row is not None, "v50 工件表未随 schema 链就绪"
        finally:
            store.close()
