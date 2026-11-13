# -*- coding: utf-8 -*-
"""C2 工件级内容地址不可变存储（specs/2026-11-12 §18）：write-once＋校验和＋按哈希读。

红：篡改存储字节后读面静默接受 / 同键异内容静默覆盖 / 未知种类静默收下。
绿：幂等零二次写＋篡改显式拒（drift/ValueError）＋未知种类 ValueError＋元数据清单无字节。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.artifact_store import (
    getArtifact,
    listArtifacts,
    latestArtifact,
    putArtifact,
    sha256Of,
    verifyArtifact,
)


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    yield s
    s.close()


class TestArtifactStore:
    def test_putAndGetRoundTrip(self, store):
        content = b'<?xml version="1.0"?><rdf:RDF>...</rdf:RDF>'
        rec = putArtifact(store, "rdf_import", content, sourceRef="import-rdf", agentId="a1")
        assert rec["created"] is True
        assert rec["sha256"] == sha256Of(content)
        assert getArtifact(store, rec["sha256"]) == content

    def test_writeOnceSameContentIdempotent(self, store):
        content = b"same-bytes"
        first = putArtifact(store, "domain_pack", content, sourceRef="p1")
        second = putArtifact(store, "domain_pack", content, sourceRef="p1")
        assert first["sha256"] == second["sha256"]
        assert first["created"] is True and second["created"] is False
        rows = listArtifacts(store)
        assert len(rows) == 1, "同内容重放不得产生第二行（零二次写）"

    def test_unknownKindRejected(self, store):
        with pytest.raises(ValueError):
            putArtifact(store, "nope", b"x")

    def test_verifyDetectsTamper(self, store):
        content = b"artifact-body"
        rec = putArtifact(store, "rdf_import", content)
        sha = rec["sha256"]
        assert verifyArtifact(store, sha)["status"] == "ok"
        # 模拟存储层损坏：字节被改而登记键不变 → 读面/核验面显式拒，不静默换字
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE ontology_artifacts SET content = ? WHERE artifact_sha256 = ?",
                (b"tampered", sha))
        assert verifyArtifact(store, sha)["status"] == "drift"
        with pytest.raises(ValueError):
            getArtifact(store, sha)

    def test_missingHonest(self, store):
        assert getArtifact(store, "ab" * 32) is None
        assert verifyArtifact(store, "ab" * 32)["status"] == "missing"

    def test_latestArtifactByKind(self, store):
        putArtifact(store, "rdf_import", b"first", registeredAt="2026-11-13T00:00:00+00:00")
        putArtifact(store, "domain_pack", b"pack", registeredAt="2026-11-13T00:00:01+00:00")
        latest = latestArtifact(store, "rdf_import")
        assert latest is not None and latest["content"] == b"first"
        assert latestArtifact(store, "domain_pack")["content"] == b"pack"

    def test_listArtifactsMetaOnly(self, store):
        putArtifact(store, "rdf_import", b"abc", sourceRef="s1")
        rows = listArtifacts(store)
        assert len(rows) == 1
        assert rows[0]["byte_count"] == 3 and "content" not in rows[0]
