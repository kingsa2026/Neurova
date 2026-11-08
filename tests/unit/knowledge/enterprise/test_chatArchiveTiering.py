# -*- coding: utf-8 -*-
"""批 C7c 第二块：正文分档判据（方案 §9/§11/§14-C 裁定「分档最小版」）。

判据：
- **facts 侧编译期拒正文**：`chatSource=archive` 的描述符把 text 配进 object
  （column 或模板）即 MappingError——十万级行灌 facts 不可逆，编译期就拦；
  capture 面 text object 照旧合法（存量行为不破）；
- **条目链承正文**：`writeArchiveEntries` 把存档文本行写成 knowledge 条目
  （幂等键 `source=wecom_archive:<msgid>`；源钟 `source_created_at`＝sent_at；
  非文本行不建空条目；重放 duplicated 不重复建）；
- **runOnceAsync 能力钩子**：registry 不感知 chat 细节，只认 writeArchiveEntries
  能力面——存档源摄取时 facts 与条目同轮落、重放双双幂等。

夹具＝真 KnowledgeRepository(tmp)（DI 注入，不碰进程单例）＋真 KnowledgeFactStore
＋真投影库（自建自插）；e2e 经 runOnceAsync 真环，repo 经类级 monkeypatch 注入。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from neurova.channels.wecom_archive import ArchiveProjectionStore
from neurova.knowledge.enterprise.connectors_chat import (
    MEDIA_REF_COLUMN,
    ROW_COLUMNS,
    ChatChannelAdapter,
)
from neurova.knowledge.enterprise.registry import EnterpriseIngestor
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
from neurova.knowledge.repository import KnowledgeRepository
from neurova.knowledge.enterprise.schema_mapping import MappingError, validateDescriptor


def _archiveRow(seq, msgid, *, text="", mediaRef="", sentAt="2023-11-14T22:13:20+00:00",
                chatId="wrRoom1", sender="userid_a"):
    return {
        "msg_id": msgid, "chat_id": chatId,
        "chat_type": "group" if chatId.startswith("wr") else "p2p",
        "sender": sender, "sent_at": sentAt, "text": text,
        MEDIA_REF_COLUMN: mediaRef,
    }


def _storeRow(seq, msgid, **kw):
    row = {"seq": seq, "msgid": msgid, "publickey_ver": "v1", "action": "send",
           "msgtype": "text" if not kw.get("mediaRef") else "image",
           "from_id": "userid_a", "tolist": '["userid_b"]', "roomid": "wrRoom1",
           "msgtime_ms": 1700000000000 + seq, "text": "", "media_ref": ""}
    row.update(kw)
    return row


def _descriptor(**overrides):
    descriptor = {
        "sourceType": "chat", "vendor": "wecom", "chatSource": "archive",
        "columns": list(ROW_COLUMNS) + [MEDIA_REF_COLUMN],
        "logicalTable": "chat_archive",
        "subject": {"template": "chat:{chat_id}"},
        "predicate": {"termId": "spoke_in"},
        "object": {"kind": "column", "column": "sender"},
        "qualifiers": {}, "agentId": "default",
    }
    descriptor.update(overrides)
    return descriptor


def _archiveAdapter(dbPath, repo=None):
    adapter = ChatChannelAdapter(_descriptor(archiveDb=str(dbPath)), "src_archive")
    if repo is not None:
        real = ChatChannelAdapter.writeArchiveEntries

        async def withRepo(rows, tenantId="default", _self=adapter, _real=real):
            return await _real(_self, rows, tenantId=tenantId, repo=repo)

        adapter.writeArchiveEntries = withRepo  # type: ignore[method-assign]
    return adapter


# ── facts 侧编译期拒正文 ─────────────────────────────────────


def test_archive_object_column_text_is_rejected():
    with pytest.raises(MappingError) as excinfo:
        validateDescriptor(_descriptor(object={"kind": "column", "column": "text"}),
                           None)
    assert "条目链" in str(excinfo.value)


def test_archive_object_template_text_is_rejected():
    with pytest.raises(MappingError):
        validateDescriptor(_descriptor(
            object={"kind": "template", "template": "说了：{text}"}), None)


def test_capture_face_text_object_still_allowed():
    """存量 capture 面不破：text 配 object 照旧合法（分档只收紧存档面）。"""
    descriptor = _descriptor(chatSource="capture",
                             object={"kind": "column", "column": "text"})
    validateDescriptor(descriptor, None)  # 不抛即通过


# ── 条目链承正文 ─────────────────────────────────────────────


@pytest.fixture()
def repo(tmp_path):
    return KnowledgeRepository(tmp_path / "knowledge")


@pytest.mark.asyncio
async def test_write_archive_entries_writes_text_rows_only(repo, tmp_path):
    store = ArchiveProjectionStore(tmp_path / "archive.db")
    try:
        store.appendBatch([
            _storeRow(1, "m1", text="今天开会定了三件事"),
            _storeRow(2, "m2", msgtype="image", media_ref="sdkfileid_IMG_1"),
        ], nextSeq=2)
    finally:
        store.close()
    adapter = ChatChannelAdapter(_descriptor(archiveDb=str(tmp_path / "archive.db")),
                                 "src_archive")
    sendRows = (await adapter.fetchBatch(None, 10)).rows  # 钩子真契约＝fetchBatch 六列行
    outcome = await adapter.writeArchiveEntries(sendRows, repo=repo)
    assert outcome["written"] == 1 and outcome["skipped"] == 1, (
        "文本行进条目；非文本行不建空条目（结构化字段由 facts 承）")
    entry = repo.findBySource("default", "wecom_archive:m1", "default")
    assert entry is not None
    assert entry.get("content") == "今天开会定了三件事"
    assert entry.get("source_created_at") == "2023-11-14T22:13:20.001000+00:00", (
        "源钟透传：条目按业务时间可查（K-09 语义；msgtime_ms=1700000000000+seq）")


@pytest.mark.asyncio
async def test_write_archive_entries_replay_is_idempotent(repo, tmp_path):
    store = ArchiveProjectionStore(tmp_path / "archive.db")
    try:
        store.appendBatch([_storeRow(1, "m1", text="重放我")], nextSeq=1)
    finally:
        store.close()
    adapter = ChatChannelAdapter(_descriptor(archiveDb=str(tmp_path / "archive.db")),
                                 "src_archive")
    sendRows = (await adapter.fetchBatch(None, 10)).rows
    first = await adapter.writeArchiveEntries(sendRows, repo=repo)
    second = await adapter.writeArchiveEntries(sendRows, repo=repo)
    assert first["written"] == 1
    assert second["written"] == 0 and second["duplicated"] == 1, (
        "幂等键 source=wecom_archive:<msgid>：重放不重复建条目")


@pytest.mark.asyncio
async def test_capture_face_has_no_entry_writer(repo):
    adapter = ChatChannelAdapter(
        {"sourceType": "chat", "vendor": "wecom", "chatSource": "capture",
         "columns": list(ROW_COLUMNS) + [MEDIA_REF_COLUMN]}, "src_capture")
    outcome = await adapter.writeArchiveEntries(
        [_archiveRow(1, "m1", text="x")], repo=repo)
    assert outcome.get("applied") is False, (
        "capture 面无条目写入：applied=False 且三计数全零（skipped 是计数不是旗标）")
    assert (outcome["written"], outcome["duplicated"], outcome["skipped"]) == (0, 0, 0)


# ── runOnceAsync 能力钩子（facts 与条目同轮、双双幂等）──────


def test_run_once_ingests_facts_and_entries_together(tmp_path, monkeypatch):
    dbPath = tmp_path / "archive.db"
    store = ArchiveProjectionStore(dbPath)
    try:
        store.appendBatch([
            _storeRow(1, "m1", text="正文一"),
            _storeRow(2, "m2", text="正文二"),
            _storeRow(3, "m3", msgtype="image", media_ref="sdkfileid_IMG_1"),
        ], nextSeq=3)
    finally:
        store.close()

    factStore = KnowledgeFactStore(str(tmp_path / "facts.db"))
    try:
        termRegistry = OntologyTermRegistry(factStore)
        termRegistry.registerMany([{"termId": "spoke_in", "kind": "relation"}])
        ingestor = EnterpriseIngestor(factStore, registry=termRegistry)

        testRepo = KnowledgeRepository(tmp_path / "knowledge")
        real = ChatChannelAdapter.writeArchiveEntries

        async def patched(self, rows, tenantId="default"):
            return await real(self, rows, tenantId=tenantId, repo=testRepo)

        monkeypatch.setattr(ChatChannelAdapter, "writeArchiveEntries", patched)

        ingestor.saveConfig("default", "src_archive", _descriptor(archiveDb=str(dbPath)),
                            enabled=True)
        first = asyncio.run(ingestor.runOnceAsync("default", "src_archive"))
        assert first["admitted"] == 3, "三行 send 全过咽喉（object=sender 结构化，正文不入 facts）"
        assert first["entries"]["written"] == 2, "两文本行进条目，图片行跳过"
        entry = testRepo.findBySource("default", "wecom_archive:m1", "default")
        assert entry is not None and entry.get("content") == "正文一"

        replay = asyncio.run(ingestor.runOnceAsync("default", "src_archive"))
        assert replay["admitted"] == 0, "facts 侧咽喉内容键幂等"
        assert replay["entries"] == {"written": 0, "duplicated": 0, "skipped": 0}, (
            "重放轮游标已推进、无行可取，钩子不空转；条目幂等由单测档钉住")
    finally:
        factStore.close()
