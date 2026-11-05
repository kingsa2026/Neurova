# -*- coding: utf-8 -*-
"""C5 红灯：事件摘要索引增强（SAG 对比候选 C5，2026-11-05）。

对照点（SAG 对比 §2.1）：对方把 chunk 经 LLM 压成语义事件（title+summary）
作索引主载体——检索召回从「字面重叠」升到「语义事件」。本仓现状：索引输入
是原文切片，无事件层。

契约（NEUROVA_KB_EVENT_SUMMARY 门控，默认 off＝旧行为逐位）：
- 写面 `extract_event_summary`：LLM 把条目压成一句事件句写回
  `event_summary` 字段（update 白名单放行＋登记 reindex）；无 LLM 如实跳过
- 读面 `build_index_content` 第四参（默认空＝逐位不变）——TF-IDF 分片/
  BM25/FTS 三条词法路同源；向量 `embeddingText` 拼摘要（指纹驱动重算）
"""
from __future__ import annotations

import pytest

from neurova.knowledge.splitter import build_index_content
from neurova.knowledge.vector_index import embeddingText

MODULE_INGESTION = "neurova.api.endpoints.knowledge_common"
AGENT = "c5-test"
ALICE = {"user_id": "u1", "tenant_id": "default"}


def test_buildIndexContent_defaultUnchanged():
    """默认（无摘要）：四参缺省时输出逐位等于旧三参行为。"""
    assert build_index_content("T", "C") == "T\nC"
    assert build_index_content("T", "C", "H") == "T\nH\nC"


def test_buildIndexContent_carriesSummary():
    """开闸产物：摘要插在标题之后、上下文头之前（索引文本的语义锚位）。"""
    assert build_index_content("T", "C", "H", event_summary="S") == "T\nS\nH\nC"
    assert build_index_content("", "C", "", event_summary="S") == "S\nC"


def test_embeddingText_carriesSummary():
    """向量嵌入文本单点：摘要拼在标题与正文之间；无摘要逐位不变。"""
    assert embeddingText({"title": "T", "content": "C"}) == "T\nC"
    assert embeddingText({"title": "T", "content": "C", "event_summary": "S"}) == "T\nS\nC"


def test_lexicalRoutes_hitViaSummary(tmp_path, monkeypatch):
    """词法路端到端：查询词只存在于事件摘要时也能命中（摘要进索引输入）。"""
    monkeypatch.delenv("NEUROVA_KB_EVENT_SUMMARY", raising=False)
    from neurova.knowledge.hybrid import hybrid_search_knowledge
    from neurova.knowledge.repository import KnowledgeRepository

    repo = KnowledgeRepository(str(tmp_path / "kb"))
    repo.create_knowledge(
        AGENT, "无关标题", "别的领域内容，不含查询词", knowledge_id="k1",
        owner_user_id="u1",
    )
    # 摘要写回（白名单）＋登记 reindex（分片更新）
    assert repo.update_knowledge(AGENT, "k1", {"event_summary": "青海湖景区海拔三千米高原湖泊"})
    hits = hybrid_search_knowledge(
        repo, ALICE, "高原湖泊 海拔", limit=3, agent_id=AGENT, vector_index=None,
    )
    assert "k1" in [h["knowledge_id"] for h in hits], (
        "查询词只在事件摘要里时词法路必须仍可命中（摘要进索引输入）"
    )


def test_updateWhitelist_carriesEventSummary(tmp_path):
    """update 白名单放行 event_summary（此前被白名单丢弃，写不进条目）。"""
    from neurova.knowledge.repository import KnowledgeRepository

    repo = KnowledgeRepository(str(tmp_path / "kb"))
    repo.create_knowledge(
        AGENT, "标题", "正文", knowledge_id="k1", owner_user_id="u1",
    )
    assert repo.update_knowledge(AGENT, "k1", {"event_summary": "一句摘要"})
    _agent, item = repo.find_item("k1")
    assert item.get("event_summary") == "一句摘要", (
        "event_summary 必须进 update 白名单（否则摘要永远写不回条目）"
    )


def test_extractEventSummary_disabledByDefault(monkeypatch, tmp_path):
    from neurova.api.endpoints.knowledge_common import extract_event_summary

    monkeypatch.delenv("NEUROVA_KB_EVENT_SUMMARY", raising=False)
    assert extract_event_summary(
        {"knowledge_id": "k1"}, None, AGENT,
        llm_call=lambda prompt: "一句摘要",
    ) == "skipped_disabled"


def test_extractEventSummary_extractsAndWrites(monkeypatch, tmp_path):
    """开闸＋LLM：摘要写回条目（走 update 白名单与 reindex 登记同一管线）。"""
    from neurova.api.endpoints.knowledge_common import extract_event_summary
    from neurova.knowledge.repository import KnowledgeRepository

    monkeypatch.setenv("NEUROVA_KB_EVENT_SUMMARY", "on")
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    repo.create_knowledge(
        AGENT, "青海湖", "青海湖是高原湖泊", knowledge_id="k1", owner_user_id="u1",
    )
    monkeypatch.setattr(
        "neurova.knowledge.repository.get_knowledge_repository", lambda: repo,
    )
    state = extract_event_summary(
        {"knowledge_id": "k1", "title": "青海湖", "content": "青海湖是高原湖泊"},
        None, AGENT, llm_call=lambda prompt: "青海湖景区是海拔三千米的高原湖泊",
    )
    assert state == "extracted"
    _agent, item = repo.find_item("k1")
    assert item.get("event_summary") == "青海湖景区是海拔三千米的高原湖泊"


def test_extractEventSummary_noLlmSkips(monkeypatch):
    from neurova.api.endpoints.knowledge_common import extract_event_summary

    monkeypatch.setenv("NEUROVA_KB_EVENT_SUMMARY", "on")
    assert extract_event_summary(
        {"knowledge_id": "k1"}, None, AGENT, llm_call=None,
    ) == "skipped_no_llm"
