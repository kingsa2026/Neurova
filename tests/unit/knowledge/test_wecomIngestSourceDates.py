# -*- coding: utf-8 -*-
"""P1-5（审计 2026-11-04）：企业微信入站边界丢源时间。

缺陷：批 TA 只给 knowledge_ingestion.py 这条摄取边界接了源时间（批 TA），
ingest_bridge 这条并行边界消费同一 parse_document 产物却未透传——
wecom 条目三时间戳恒空 ⇒ TB 对它永不触发、TD① 按源时间过滤全排除、
前端源时间列恒空。

契约（绿灯态）：wecom 入库条目与文件导入同口径——管线元数据优先
（created_at/modified_at），缺失回退抓取（入库）时刻；两参真正落到
条目字段。公共口径单源（resolveSourceDates），不许第二份定义。
"""
from types import SimpleNamespace

import pytest

from neurova.knowledge import ingest_bridge as bridge_mod
from neurova.knowledge.repository import KnowledgeRepository


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    r = KnowledgeRepository(str(tmp_path / "kb"))
    r._items.clear()
    monkeypatch.setattr(bridge_mod, "get_knowledge_repository", lambda: r)
    return r


def _patchParse(monkeypatch, metadata):
    parsed = SimpleNamespace(
        content="企微文档正文", metadata=metadata, chunks=[], parents=[],
        ingest_time="2026-11-04T09:00:00+00:00", source_type="wecom",
        source_path="wecom:room1:msg1", doc_id="doc-1",
    )
    monkeypatch.setattr(bridge_mod, "parse_document", lambda *a, **k: parsed)


async def _ingest():
    """直接驱动真 _ingestPayload 协程（queue/transport 不入径，传桩对象）。"""
    bridge = bridge_mod.KnowledgeIngestBridge(queue=object(), transport=object())
    message = SimpleNamespace(sender_id="user-1")
    metadata = {"tenant_id": "default"}
    event = {"event_id": "wecom:room1:msg1"}
    return await bridge._ingestPayload(
        message, metadata, "a1", "default", "wecom:room1:msg1", event,
    )


@pytest.mark.asyncio
async def test_wecomCarriesSourceDatesFromPipelineMetadata(repo, monkeypatch):
    _patchParse(monkeypatch, {
        "title": "企微文档",
        "created_at": "2024-03-01T08:00:00+00:00",
        "modified_at": "2026-01-02T10:00:00+00:00",
    })
    result = await _ingest()
    assert result.get("status") == "accepted", result
    item = repo._items["a1"][0]
    assert item["source_created_at"] == "2024-03-01T08:00:00+00:00", "企微边界丢了源创建时间"
    assert item["source_modified_at"] == "2026-01-02T10:00:00+00:00", "企微边界丢了源修改时间"


@pytest.mark.asyncio
async def test_wecomMissingMetaFallsBackToIngestTime(repo, monkeypatch):
    """与文件导入同口径：元数据缺失回退 ingest_time（诚实记最早已知时间）。"""
    _patchParse(monkeypatch, {"title": "企微文档"})
    result = await _ingest()
    assert result.get("status") == "accepted", result
    item = repo._items["a1"][0]
    assert item["source_created_at"] == "2026-11-04T09:00:00+00:00"
    assert item["source_modified_at"] == "2026-11-04T09:00:00+00:00"
