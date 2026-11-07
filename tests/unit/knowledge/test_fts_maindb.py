# -*- coding: utf-8 -*-
"""K-09 FTS 搬主库（台账 §6-568②，2026-11-07 裁定：FTS 搬进 foundation 主库）。

裁定前状态：knowledge_fts.db 是独立库文件，foundation 的 user_version 迁移链
物理上够不着（一个 SQLite 文件一个版本域）；fts_index 自建 DDL 是第二份 schema。
裁定后：FTS 两表（knowledge_fts_docs / knowledge_fts 虚表）进 v37 迁移，
knowledge_fts_docs 顺带补 source_modified_at 列（条目源钟进倒排面），
旧独立库文件一次性退役（派生索引，可由 reconcile 全量重建）。

列的消费方＝search() 的确定性同分 tie-break：同分命中里源文档更新者排前。
"""

from __future__ import annotations

import sqlite3

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.narratives import FOUNDATION_DB_NAME


@pytest.fixture
def dbPath(tmp_path):
    store = KnowledgeFactStore(str(tmp_path / FOUNDATION_DB_NAME))
    path = str(tmp_path / FOUNDATION_DB_NAME)
    store.close()
    return path


def _item(knowledgeId: str, title: str, body: str,
          sourceModifiedAt: str = "", updatedAt: float = 0.0) -> dict:
    return {
        "knowledge_id": knowledgeId,
        "title": title,
        "content": body,
        "visibility": "public",
        "owner_user_id": "u1",
        "tenant_id": "default",
        "category": "",
        "tags": [],
        "source": "",
        "updated_at": updatedAt,
        "lifecycle_status": "active",
        "valid_until": "",
        "source_modified_at": sourceModifiedAt,
    }


class TestV37Migration:
    def test_ftsTablesLiveInFoundationDb(self, dbPath):
        from neurova.knowledge.fts_index import KnowledgeFtsIndex

        conn = sqlite3.connect(dbPath)
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        cols = {r[1] for r in conn.execute("PRAGMA table_info(knowledge_fts_docs)")}
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        assert version == 37, "v37 后 FTS 两表归 foundation 迁移域"
        assert {"knowledge_fts_docs", "knowledge_fts"} <= names, "FTS 两表在主库"
        assert "source_modified_at" in cols, "docs 表带源钟列"

    def test_reopeningExistingDbStillUpgrades(self, dbPath, tmp_path):
        from neurova.knowledge.fts_index import KnowledgeFtsIndex

        idx = KnowledgeFtsIndex(dbPath)
        idx.close()
        conn = sqlite3.connect(dbPath)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        assert version == 37

    def test_noSeparateDbFileIsCreated(self, dbPath, tmp_path):
        from neurova.knowledge.fts_index import KnowledgeFtsIndex

        idx = KnowledgeFtsIndex(dbPath)
        try:
            idx.reconcile({"default": [_item("k1", "标题", "蜂群并发成本护栏正文")]})
            assert idx.search("蜂群"), "索引在主库上可用"
        finally:
            idx.close()
        assert not (tmp_path / "knowledge_fts.db").exists(), \
            "不再另立 knowledge_fts.db（schema 单一事实源）"


class TestSourceClockInFts:
    def test_sourceModifiedAtIndexedPerDoc(self, dbPath):
        from neurova.knowledge.fts_index import KnowledgeFtsIndex

        idx = KnowledgeFtsIndex(dbPath)
        try:
            idx.reconcile({"default": [
                _item("k1", "客户偏好", "客户X购买自行车",
                      sourceModifiedAt="2026-01-01T00:00:00"),
            ]})
            conn = sqlite3.connect(dbPath)
            row = conn.execute(
                "SELECT source_modified_at FROM knowledge_fts_docs"
                " WHERE knowledge_id='k1'").fetchone()
            conn.close()
            assert row and row[0] == "2026-01-01T00:00:00"
        finally:
            idx.close()

    def test_sameScoreTieBreaksByNewerSource(self, dbPath):
        """同分命中：源文档更新者排前（列的消费方＝确定性 tie-break）。"""
        from neurova.knowledge.fts_index import KnowledgeFtsIndex

        idx = KnowledgeFtsIndex(dbPath)
        try:
            body = "客户X购买自行车偏好记录"
            idx.reconcile({"default": [
                _item("k_old", "客户偏好", body,
                      sourceModifiedAt="2026-01-01T00:00:00"),
                _item("k_new", "客户偏好", body,
                      sourceModifiedAt="2026-11-01T00:00:00"),
            ]})
            hits = idx.search("客户X购买自行车")
            ids = [str(h["id"]) for h in hits]
            assert set(ids) >= {"k_old", "k_new"}
            oldPos, newPos = ids.index("k_old"), ids.index("k_new")
            assert newPos < oldPos, \
                "同分 tie-break 按源钟：源文档更新的命中排前（%s vs %s）" % (ids, None)
        finally:
            idx.close()

    def test_sourceClockChangeReindexes(self, dbPath):
        """源钟变化也是指纹变化：重入库后倒排面的源钟跟着走。"""
        from neurova.knowledge.fts_index import KnowledgeFtsIndex

        idx = KnowledgeFtsIndex(dbPath)
        try:
            idx.reconcile({"default": [
                _item("k1", "客户偏好", "正文", sourceModifiedAt="2026-01-01T00:00:00"),
            ]})
            changed = idx.reconcile({"default": [
                _item("k1", "客户偏好", "正文", sourceModifiedAt="2026-11-01T00:00:00"),
            ]})
            assert changed["changed"] == 1, "源钟前移触发重索引"
            conn = sqlite3.connect(dbPath)
            row = conn.execute(
                "SELECT source_modified_at FROM knowledge_fts_docs"
                " WHERE knowledge_id='k1'").fetchone()
            conn.close()
            assert row[0] == "2026-11-01T00:00:00"
        finally:
            idx.close()


class TestLegacySeparateDbRetired:
    def test_legacyKnowledgeFtsDbFileRemoved(self, tmp_path, monkeypatch):
        """旧独立库文件一次性退役：_ensureFts 就位后 best-effort 删除。"""
        monkeypatch.setenv("NEUROVA_KB_NARRATIVE_STORE", "on")
        from neurova.knowledge.repository import KnowledgeRepository

        repo_dir = tmp_path / "kb"
        legacy = repo_dir / "knowledge_fts.db"
        repo_dir.mkdir(parents=True, exist_ok=True)
        legacy_conn = sqlite3.connect(str(legacy))
        legacy_conn.execute("CREATE TABLE t (x)")
        legacy_conn.commit()
        legacy_conn.close()

        repo = KnowledgeRepository(str(repo_dir))
        repo._ensureFts()
        assert not legacy.exists(), "旧派生索引文件退役（可由 reconcile 重建）"
