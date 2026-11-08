# -*- coding: utf-8 -*-
"""批 C7c 第三块：媒体触发面（方案 §10-甲裁定：独立触发、逐条可控、可限流）。

官方口径（文档 91774 实证，2026-11-09 浏览器渲染取全文）：
- `GetMediaData(sdk, indexbuf, sdkfileid, proxy, passwd, int timeout, MediaData_t*)`
  ——**indexbuf 在 sdkfileid 之前**、timeout 是 int、输出是 MediaData_t* 句柄；
- 工具五件：NewMediaData/FreeMediaData/GetOutIndexBuf/GetData/IsMediaDataFinish；
- 分片单次最大 512K；首次 indexbuf 空、后续填上次 GetOutIndexBuf 返回；
  IsMediaDataFinish=1 完成。

判据：
- **续传环**（真 Handle 循环＋假 ctypes lib）：首调 indexbuf 空、后续精确喂上一次
  GetOutIndexBuf 返回；分片按序拼接；完成即止；
- **引用过期独立读数**：ret≠0 → `ArchiveMediaUnavailable`（与一般失败分开，
  端点 502 原话；方案 §10 附带约束：不许把「有引用」报成「附件可检索」）；
- **未完成且无续传索引 → 异常**；**分片数超上限 → 异常**（防续传环失控）；
- **缺导出点名**：库缺 GetMediaData 族任一导出即 ArchiveSdkError；
- **stageArchiveMedia**：暂存落盘＋投影回写 media_staged_path（「已采集」机器可判）、
  already_staged 幂等、no_media 诚实、引用过期原样上抛；
- **端点**：admin 门 403／非存档源 400／凭据未就绪 409／无引用 404／staged 200／
  引用过期 502（SDK 经 buildArchiveSdkForContext 注入假件，双态登记口径）。
"""

from __future__ import annotations

import asyncio
import ctypes
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import knowledge_enterprise as KE
from neurova.channels import wecom_archive
from neurova.knowledge.enterprise.registry import EnterpriseIngestor
from neurova.channels.wecom_archive import (
    ARCHIVE_MEDIA_MAX_CHUNKS,
    ArchiveMediaUnavailable,
    ArchiveProjectionStore,
    ArchiveSdkError,
    stageArchiveMedia,
)


# ── 假 ctypes lib：驱动真 Handle.getMediaData 续传环 ─────────


class FakeMediaLib:
    """按官方签名形状提供 GetMediaData 族；分片与续传索引逐调推进。"""

    def NewMediaData(self):
        return 1

    def FreeMediaData(self, mediaPtr):
        return None

    def __init__(self, chunks, outIndexes, failOnCall=None):
        self._chunks = list(chunks)
        self._indexes = list(outIndexes)
        self._failOnCall = failOnCall
        self.calls = []
        self._i = -1

    def GetMediaData(self, handle, indexBuf, sdkfileid, proxy, passwd, timeout, mediaPtr):
        self._i += 1
        self.calls.append({"indexbuf": bytes(indexBuf or b""),
                           "sdkfileid": bytes(sdkfileid or b"")})
        if self._failOnCall is not None and self._i == self._failOnCall:
            return 9
        return 0

    def GetData(self, mediaPtr):
        return self._chunks[self._i]

    def GetOutIndexBuf(self, mediaPtr):
        return self._indexes[self._i]

    def IsMediaDataFinish(self, mediaPtr):
        return 1 if self._i >= len(self._chunks) - 1 else 0


def _handleWith(lib):
    handle = wecom_archive.ArchiveSdkHandle.__new__(wecom_archive.ArchiveSdkHandle)
    handle._lib = lib
    handle._handle = ctypes.c_void_p(0)
    return handle


def test_media_continuation_loop_concatenates_and_feeds_index():
    lib = FakeMediaLib(chunks=[b"AAAA", b"BBBB", b"CC"],
                       outIndexes=[b"idx1", b"idx2", b""])
    handle = _handleWith(lib)
    data = handle.getMediaData("sdkfileid_X", timeout=10)
    assert data == b"AAAABBBBCC"
    assert [c["indexbuf"] for c in lib.calls] == [b"", b"idx1", b"idx2"], (
        "首调 indexbuf 空、后续精确喂上一次 GetOutIndexBuf 返回（官方 §91774）")
    assert all(c["sdkfileid"] == b"sdkfileid_X" for c in lib.calls)


def test_media_ret_nonzero_is_media_unavailable():
    lib = FakeMediaLib(chunks=[b"x"], outIndexes=[b""], failOnCall=0)
    handle = _handleWith(lib)
    with pytest.raises(ArchiveMediaUnavailable) as excinfo:
        handle.getMediaData("expired_ref")
    assert "过期" in str(excinfo.value) or "不可达" in str(excinfo.value)


def test_media_unfinished_without_index_raises():
    lib = FakeMediaLib(chunks=[b"partial"], outIndexes=[b""])
    lib.IsMediaDataFinish = lambda mediaPtr: 0  # 永未完成
    handle = _handleWith(lib)
    with pytest.raises(ArchiveSdkError):
        handle.getMediaData("ref")


def test_media_chunk_overflow_guard():
    lib = FakeMediaLib(chunks=[b"x"] * (ARCHIVE_MEDIA_MAX_CHUNKS + 2),
                       outIndexes=[b"idx"] * (ARCHIVE_MEDIA_MAX_CHUNKS + 2))
    lib.IsMediaDataFinish = lambda mediaPtr: 0
    handle = _handleWith(lib)
    with pytest.raises(ArchiveSdkError) as excinfo:
        handle.getMediaData("ref")
    assert "超上限" in str(excinfo.value)


def test_missing_media_exports_named(capsys):
    class LibWithoutMedia:
        def __getattr__(self, name):
            raise AttributeError(name)

    with pytest.raises(ArchiveSdkError) as excinfo:
        wecom_archive._requireExports(LibWithoutMedia(),
                                      wecom_archive.ArchiveSdkHandle._EXPORTS)
    assert "GetMediaData" in str(excinfo.value)


# ── stageArchiveMedia ────────────────────────────────────────


def _seedStore(tmp_path, msgid="m1", mediaRef="sdk_ref_1", mediaName="report.pdf"):
    store = ArchiveProjectionStore(tmp_path / "archive.db")
    try:
        store.appendBatch([{
            "seq": 1, "msgid": msgid, "publickey_ver": "v1", "action": "send",
            "msgtype": "file", "from_id": "a", "tolist": "[]",
            "roomid": "wrR", "msgtime_ms": 1, "text": "",
            "media_ref": mediaRef, "media_name": mediaName,
        }], nextSeq=1)
    finally:
        store.close()
    return tmp_path / "archive.db"


class FakeStageSdk:
    def __init__(self, payload=b"PDF-bytes", error=None):
        self._payload = payload
        self._error = error
        self.requested = []

    def getMediaData(self, sdkfileid, timeout=30):
        self.requested.append(sdkfileid)
        if self._error is not None:
            raise self._error
        return self._payload

    def close(self):
        return None


def test_stage_writes_file_and_records_staged_path(tmp_path):
    dbPath = _seedStore(tmp_path)
    staging = tmp_path / "stage"
    outcome = stageArchiveMedia(dbPath, "m1", FakeStageSdk(b"PDF-bytes"),
                                stagingRoot=staging)
    assert outcome["status"] == "staged" and outcome["size"] == len(b"PDF-bytes")
    assert Path(outcome["path"]).read_bytes() == b"PDF-bytes"
    assert outcome["path"].endswith(".pdf"), "media_name 携带原始扩展名（下游解析按型辨类）"
    record = wecom_archive.readArchiveMediaRecord(dbPath, "m1")
    assert record["media_staged_path"] == outcome["path"], (
        "「已采集」机器可判：media_staged_path 回写投影")


def test_stage_idempotent_when_already_staged(tmp_path):
    dbPath = _seedStore(tmp_path)
    staging = tmp_path / "stage"
    first = stageArchiveMedia(dbPath, "m1", FakeStageSdk(), stagingRoot=staging)
    second = stageArchiveMedia(dbPath, "m1", FakeStageSdk(), stagingRoot=staging)
    assert first["status"] == "staged"
    assert second["status"] == "already_staged", "重触发幂等（不重复取回不重复落盘）"


def test_stage_no_media_readout(tmp_path):
    dbPath = _seedStore(tmp_path, msgid="m_text", mediaRef="")
    outcome = stageArchiveMedia(dbPath, "m_text", FakeStageSdk(),
                                stagingRoot=tmp_path / "stage")
    assert outcome == {"status": "no_media", "msgid": "m_text"}
    outcome2 = stageArchiveMedia(tmp_path / "missing.db", "m1", FakeStageSdk())
    assert outcome2["status"] == "no_media", "投影库未落盘同样是诚实 no_media"


def test_stage_expired_reference_propagates(tmp_path):
    dbPath = _seedStore(tmp_path)
    with pytest.raises(ArchiveMediaUnavailable):
        stageArchiveMedia(dbPath, "m1",
                          FakeStageSdk(error=ArchiveMediaUnavailable("ret=3 过期")),
                          stagingRoot=tmp_path / "stage")
    record = wecom_archive.readArchiveMediaRecord(dbPath, "m1")
    assert record["media_staged_path"] == "", (
        "取回失败不落半状态：引用仍在（存档记录），「已采集」不成立")


# ── 端点 ─────────────────────────────────────────────────────


@pytest.fixture()
def mediaApp(tmp_path, monkeypatch):
    dbPath = _seedStore(tmp_path)
    from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    factStore = KnowledgeFactStore(str(tmp_path / "facts.db"))
    termRegistry = OntologyTermRegistry(factStore)
    termRegistry.registerMany([{"termId": "spoke_in", "kind": "relation"}])
    ingestor = EnterpriseIngestor(factStore, registry=termRegistry)
    from neurova.knowledge.enterprise.registry import getSourceRegistry

    monkeypatch.setattr(KE, "_parts",
                        lambda: (ingestor, getSourceRegistry(), factStore))

    app = FastAPI()
    app.include_router(KE.router)
    app.dependency_overrides[KE.get_current_user_or_service] = lambda: {
        "user_id": "u", "role": "admin", "tenant_id": "default"}

    monkeypatch.setattr(
        wecom_archive, "_archiveWorkerContexts",
        lambda agentId="default": [{
            "agentId": "default", "ready": True, "sdkPath": "fake",
            "corpid": "corp", "secret": "s", "keyMap": {},
            "roomAllowlist": [], "userAllowlist": []}])
    monkeypatch.setattr(
        wecom_archive, "buildArchiveSdkForContext",
        lambda context: FakeStageSdk(b"PDF-bytes"))
    descriptor = {
        "sourceType": "chat", "vendor": "wecom", "chatSource": "archive",
        "columns": ["msg_id", "chat_id", "chat_type", "sender", "sent_at",
                    "text", "media_ref"],
        "logicalTable": "chat_archive",
        "subject": {"template": "chat:{chat_id}"},
        "predicate": {"termId": "spoke_in"},
        "object": {"kind": "column", "column": "sender"},
        "qualifiers": {}, "agentId": "default", "archiveDb": str(dbPath)}
    ingestor.saveConfig("default", "src_archive", descriptor, enabled=True)
    return app, dbPath, ingestor


def test_endpoint_stages_media(tmp_path, mediaApp):
    app, _db, _ingestor = mediaApp
    client = TestClient(app)
    resp = client.post("/enterprise/sources/src_archive/media",
                       json={"msg_id": "m1"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "staged" and data["size"] == len(b"PDF-bytes")


def test_endpoint_gates(tmp_path, mediaApp, monkeypatch):
    app, _db, ingestor = mediaApp
    client = TestClient(app)
    # 非 admin 403（第二套覆盖）
    app2 = FastAPI()
    app2.include_router(KE.router)
    app2.dependency_overrides[KE.get_current_user_or_service] = lambda: {
        "user_id": "u", "role": "viewer", "tenant_id": "default"}
    client2 = TestClient(app2)
    assert client2.post("/enterprise/sources/src_archive/media",
                        json={"msg_id": "m1"}).status_code == 403
    # 非存档源 400
    ingestor.saveConfig("default", "src_capture", {
        "sourceType": "chat", "vendor": "wecom", "chatSource": "capture",
        "columns": ["msg_id", "chat_id", "chat_type", "sender", "sent_at",
                    "text", "media_ref"],
        "logicalTable": "chat_capture",
        "subject": {"template": "chat:{msg_id}"},
        "predicate": {"termId": "spoke_in"},
        "object": {"kind": "column", "column": "sender"},
        "qualifiers": {}, "agentId": "default"}, enabled=True)
    assert client.post("/enterprise/sources/src_capture/media",
                       json={"msg_id": "m1"}).status_code == 400
    # 无附件引用 404
    assert client.post("/enterprise/sources/src_archive/media",
                       json={"msg_id": "nope"}).status_code == 404


def test_endpoint_expired_reference_is_502(tmp_path, mediaApp, monkeypatch):
    app, dbPath, _ingestor = mediaApp
    client = TestClient(app)
    monkeypatch.setattr(
        wecom_archive, "buildArchiveSdkForContext",
        lambda context: FakeStageSdk(
            error=ArchiveMediaUnavailable("GetMediaData 失败 ret=3——引用过期")))
    resp = client.post("/enterprise/sources/src_archive/media",
                       json={"msg_id": "m1"})
    assert resp.status_code == 502
    assert "过期" in resp.json()["detail"], "引用过期独立读数（§10 附带约束）"
    record = wecom_archive.readArchiveMediaRecord(dbPath, "m1")
    assert record["media_staged_path"] == ""
