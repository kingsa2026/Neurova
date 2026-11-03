# -*- coding: utf-8 -*-
"""批 TA：知识库三时间戳细分契约——源创建/源修改/入库。

立项理由（docs/specs/2026-11-04-知识库三时间戳与时间感知消费面设计.md 批 TA）：
文档管线早已抽取源文档的 created_at/modified_at（docx core properties、PDF
creationDate/modDate），但 `create_knowledge()` 不收这两个值——**在摄取边界
即丢**，条目只有入库时刻却顶着"创建时间"的名字展示。

契约（T-E 等拍板随批落死）：
- `source_created_at` / `source_modified_at`：源文档自身时间，ISO/原串透传，
  缺失留空（沿用管线"失败一律空值，不猜"哲学——不回退文件 mtime 编造）；
- `created_at`/`updated_at` 语义不变＝入库/条目更新时刻（存量 37 行不动）。
"""
import pytest

from neurova.knowledge.repository import KnowledgeRepository
from neurova.api.endpoints.knowledge_common import item_response


@pytest.fixture()
def repo(tmp_path):
    return KnowledgeRepository(str(tmp_path))


class TestContractFields:
    def test_createKnowledgeCarriesSourceDates(self, repo):
        item = repo.create_knowledge(
            agent_id="a1", title="带源时间的文档", content="正文",
            source="import:课件.pdf", source_type="pdf",
            source_created_at="2024-03-01T08:00:00+00:00",
            source_modified_at="2026-01-02T10:00:00+00:00",
        )
        assert item["source_created_at"] == "2024-03-01T08:00:00+00:00"
        assert item["source_modified_at"] == "2026-01-02T10:00:00+00:00"
        # 入库时间的既有语义不变：created_at 是条目入库时刻（epoch float），
        # 不被源文档时间顶掉
        assert isinstance(item["created_at"], float) and item["created_at"] > 0
        assert item["created_at"] != item["source_created_at"]

    def test_sourceDatesDefaultEmpty(self, repo):
        """缺失不猜：无源时间的来源（手工创建/网页未考）留空串。"""
        item = repo.create_knowledge(agent_id="a1", title="手工条目", content="正文")
        assert item["source_created_at"] == ""
        assert item["source_modified_at"] == ""

    def test_migrateEntryFillsDefaults(self, repo):
        """存量行（37 条）迁移补齐默认空值——既有语义与展示不受影响。"""
        legacy = {"knowledge_id": "legacy-1", "title": "旧条目", "content": "旧正文"}
        repo._migrate_entry(legacy)
        assert legacy["source_created_at"] == ""
        assert legacy["source_modified_at"] == ""

    def test_itemResponseProjectsSourceDates(self, repo):
        item = repo.create_knowledge(
            agent_id="a1", title="投影", content="正文",
            source_created_at="2024-03-01T08:00:00+00:00",
            source_modified_at="2026-01-02T10:00:00+00:00",
        )
        resp = item_response(item)
        assert resp.source_created_at == "2024-03-01T08:00:00+00:00"
        assert resp.source_modified_at == "2026-01-02T10:00:00+00:00"


class TestIngestionFallback:
    def test_resolveSourceDates_prefersMetadata(self):
        from neurova.api.endpoints.knowledge_ingestion import _resolveSourceDates

        created, modified = _resolveSourceDates(
            {"created_at": "2019-01-01T00:00:00Z", "modified_at": "2025-06-01T00:00:00Z"},
            ingest_time="2026-11-04T00:00:00+00:00")
        assert (created, modified) == ("2019-01-01T00:00:00Z", "2025-06-01T00:00:00Z")

    def test_resolveSourceDates_fallsBackToIngestTime(self):
        """网页/无元数据来源：诚实记抓取（入库）时刻为源时间——不编造更早的历史。"""
        from neurova.api.endpoints.knowledge_ingestion import _resolveSourceDates

        created, modified = _resolveSourceDates({}, ingest_time="2026-11-04T00:00:00+00:00")
        assert created == modified == "2026-11-04T00:00:00+00:00"

    def test_resolveSourceDates_emptyIngestTimeStaysEmpty(self):
        from neurova.api.endpoints.knowledge_ingestion import _resolveSourceDates

        assert _resolveSourceDates({}, ingest_time="") == ("", "")
