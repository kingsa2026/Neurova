# -*- coding: utf-8 -*-
"""条目级精确去重（A1）与元数据过滤（A3）的判据咬合。

A1 验收（计划 §5 Batch A1）：同租户同文重复导入返回既有条目并追加来源证据，
不新建记录；空白/全半角差异不算不同文档；跨租户同文不互斥；默认关闭时行为逐字不变。
A3 验收（Batch A3）：`author/source_type/ocr_used/page_min` 过滤先于检索，
且过滤组合不越过租户边界。
"""
from __future__ import annotations

import pytest

from neurova.knowledge.repository import KnowledgeRepository

T1_USER = {"user_id": "u1", "username": "a", "role": "admin", "tenant_id": "t1"}
T2_USER = {"user_id": "u2", "username": "b", "role": "admin", "tenant_id": "t2"}


@pytest.fixture()
def repo(tmp_path):
    return KnowledgeRepository(str(tmp_path / "kb"))


class TestExactDedupe:
    def testDuplicateContentReturnsExistingEntryAndAppendsSource(self, repo):
        first = repo.create_knowledge(
            "agent", "预算口径", "2026 年预算 100 万元",
            source="wecom", source_type="im", tenant_id="t1", dedupe=True)
        second = repo.create_knowledge(
            "agent", "预算口径", "2026 年预算 100 万元",
            source="upload", source_type="pdf", tenant_id="t1", dedupe=True)

        assert second["knowledge_id"] == first["knowledge_id"]
        assert second.get("duplicate") is True
        sources = [s.get("source") for s in second.get("sources", [])]
        assert sources == ["wecom", "upload"], second.get("sources")
        assert len(repo.visible_items(T1_USER)) == 1

    def testWhitespaceAndCaseVariantsShareFingerprint(self, repo):
        first = repo.create_knowledge(
            "agent", "标题", "Alpha  Beta\t测试", source="a", tenant_id="t1", dedupe=True)
        second = repo.create_knowledge(
            "agent", "标题", "alpha beta 测试 ", source="b", tenant_id="t1", dedupe=True)

        assert second["knowledge_id"] == first["knowledge_id"]
        assert second.get("duplicate") is True

    def testSameContentDifferentTenantNotDeduped(self, repo):
        first = repo.create_knowledge(
            "agent", "同文", "同一份正文", source="s", tenant_id="t1", dedupe=True)
        second = repo.create_knowledge(
            "agent", "同文", "同一份正文", source="s", tenant_id="t2", dedupe=True)

        assert first["knowledge_id"] != second["knowledge_id"]
        assert second.get("duplicate") is not True
        assert first["tenant_id"] == "t1" and second["tenant_id"] == "t2"

    def testDefaultDedupeOffStillCreatesNewEntry(self, repo):
        first = repo.create_knowledge(
            "agent", "同文", "同一份正文", source="s", tenant_id="t1")
        second = repo.create_knowledge(
            "agent", "同文", "同一份正文", source="s", tenant_id="t1")

        assert first["knowledge_id"] != second["knowledge_id"]
        assert second.get("duplicate") is not True
        assert len(repo.visible_items(T1_USER)) == 2

    def testSameSourceEvidenceNotAppendedTwice(self, repo):
        repo.create_knowledge(
            "agent", "标题", "正文", source="wecom", source_type="im",
            source_path="/x.pdf", tenant_id="t1", dedupe=True)
        second = repo.create_knowledge(
            "agent", "标题", "正文", source="wecom", source_type="im",
            source_path="/x.pdf", tenant_id="t1", dedupe=True)

        assert second.get("duplicate") is True
        assert len(second.get("sources", [])) == 1


class TestMetadataFilters:
    @pytest.fixture()
    def seeded(self, repo):
        def _add(title, author, sourceType, ocrUsed, pageCount):
            repo.create_knowledge(
                "agent", title, "内容 " + title,
                owner_user_id="u1", tenant_id="t1", visibility="public",
                author=author, source_type=sourceType,
                ocr_used=ocrUsed, page_count=pageCount)
        _add("甲", "张三", "pdf", False, 10)
        _add("乙", "张三", "docx", True, 3)
        _add("丙", "李四", "pdf", False, 20)
        _add("丁", "李四", "url", False, None)
        return repo

    def _titles(self, items):
        return {item["title"] for item in items}

    def testFilterByAuthor(self, seeded):
        hits = seeded.visible_items(T1_USER, author="张三")

        assert self._titles(hits) == {"甲", "乙"}

    def testFilterBySourceType(self, seeded):
        hits = seeded.visible_items(T1_USER, source_type="pdf")

        assert self._titles(hits) == {"甲", "丙"}

    def testFilterByOcrUsed(self, seeded):
        hits = seeded.visible_items(T1_USER, ocr_used=True)

        assert self._titles(hits) == {"乙"}

    def testFilterByPageMinExcludesShortAndMissing(self, seeded):
        hits = seeded.visible_items(T1_USER, page_min=5)

        assert self._titles(hits) == {"甲", "丙"}

    def testSearchPathAppliesFilterBeforeRetrieval(self, seeded):
        hits = seeded.search_visible_items(
            T1_USER, "内容", author="李四", limit=10)

        assert self._titles(hits) == {"丙", "丁"}

    def testAuthorFilterDoesNotCrossTenant(self, tmp_path):
        repo = KnowledgeRepository(str(tmp_path / "kb"))
        repo.create_knowledge(
            "agent", "租户一张三文", "内容", owner_user_id="u1",
            tenant_id="t1", visibility="public", author="张三")
        repo.create_knowledge(
            "agent", "租户二张三文", "内容", owner_user_id="u2",
            tenant_id="t2", visibility="public", author="张三")

        hits = repo.visible_items(T1_USER, author="张三")

        assert self._titles(hits) == {"租户一张三文"}
