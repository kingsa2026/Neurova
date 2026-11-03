# -*- coding: utf-8 -*-
"""批 TA/TB 活体：真 docx（带 core_properties 时间）→ 真导入端点 → 三时间戳
落条目；同文件改时间重导 → 更新重入库（T-E）。

沿 tests/unit/api/test_knowledge_import.py 的既有形态：注入临时仓库到两个
叶子模块，直接调真端点协程（真管线解析真 docx，无业务对象 mock）。
"""
import io
import json

import pytest

from neurova.api.endpoints import knowledge as kb
from neurova.api.endpoints import knowledge_core as kb_core
from neurova.api.endpoints import knowledge_ingestion as kb_ingestion


def _make_docx_bytes(created, modified, paragraph):
    import docx

    d = docx.Document()
    d.add_paragraph(paragraph)
    props = d.core_properties
    props.created = created
    props.modified = modified
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


class _FakeUpload:
    content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self._data = data

    async def read(self) -> bytes:
        return self._data


@pytest.fixture()
def repo(monkeypatch, tmp_path):
    from neurova.knowledge.repository import KnowledgeRepository

    repo = KnowledgeRepository(str(tmp_path / "kb"))
    repo._items.clear()
    monkeypatch.setattr(kb_ingestion, "get_repository", lambda agent_id="default": repo)
    monkeypatch.setattr(kb_core, "get_repository", lambda agent_id="default": repo)
    return repo


@pytest.mark.asyncio
async def test_importCarriesSourceDatesFromDocxMetadata(repo):
    """真 docx 的 core_properties created/modified 经真管线落条目三时间戳。"""
    import datetime

    data = _make_docx_bytes(
        datetime.datetime(2024, 3, 1, 8, 0, 0, tzinfo=datetime.timezone.utc),
        datetime.datetime(2026, 1, 2, 10, 0, 0, tzinfo=datetime.timezone.utc),
        "活体正文：三时间戳",
    )
    result = await kb.import_knowledge_file(
        _FakeUpload("活体报告.docx", data), request=None,
        current_user={"user_id": "u1"}, agent_id="a1")
    items = result["data"]["items"]

    assert items, "导入失败"
    item = json.loads(json.dumps(items[0]))
    assert item["source_created_at"], "源创建时间丢了（摄取边界掉字段）"
    assert item["source_modified_at"], "源修改时间丢了（摄取边界掉字段）"
    assert "2024-03-01" in item["source_created_at"]
    assert "2026-01-02" in item["source_modified_at"]
    # 入库时间仍是条目时刻（epoch），两者不混淆
    assert item["created_at"] != item["source_created_at"]


@pytest.mark.asyncio
async def test_reimportWithLaterModifiedUpdatesInPlace(repo):
    """同一文件改时间重导：更新重入库（保留条目身份、旧值进 revisions）。"""
    import datetime

    v1 = _make_docx_bytes(
        datetime.datetime(2024, 3, 1, 8, 0, 0, tzinfo=datetime.timezone.utc),
        datetime.datetime(2026, 1, 2, 10, 0, 0, tzinfo=datetime.timezone.utc),
        "第一版正文",
    )
    v2 = _make_docx_bytes(
        datetime.datetime(2024, 3, 1, 8, 0, 0, tzinfo=datetime.timezone.utc),
        datetime.datetime(2026, 10, 1, 10, 0, 0, tzinfo=datetime.timezone.utc),
        "第二版正文",
    )
    first = await kb.import_knowledge_file(
        _FakeUpload("活体报告.docx", v1), request=None,
        current_user={"user_id": "u1"}, agent_id="a1")
    first = first["data"]["items"]
    second = await kb.import_knowledge_file(
        _FakeUpload("活体报告.docx", v2), request=None,
        current_user={"user_id": "u1"}, agent_id="a1")
    second = second["data"]["items"]

    assert second[0].get("source_updated") is True, "改时间重导未走更新重入库"
    assert second[0]["knowledge_id"] == first[0]["knowledge_id"], "条目身份变了"
    assert second[0]["content"].find("第二版正文") != -1, "内容没有更新"
    revs = repo.list_revisions(first[0]["knowledge_id"])
    assert any(r.get("reason") == "source_update_reingest" for r in revs), "旧值没进 revisions"
