"""渠道消息 → 知识库入站桥：文本/链接/媒体/语音、幂等与显式失败。"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from neurova.knowledge import ingest_bridge as bridge_module
from neurova.knowledge.ingest_bridge import KnowledgeIngestBridge
from neurova.knowledge.ingest_jobs import KnowledgeIngestQueue


class FakeRepo:
    def __init__(self, existing=None):
        self.existing = existing
        self.created = []

    def findBySource(self, agent_id, source, tenant_id="default"):
        return self.existing

    def create_knowledge(self, **kwargs):
        self.created.append(kwargs)
        return {"knowledge_id": "k-new", **kwargs}


def _message(kind="text", content="正文", metadata=None, message_id="m1"):
    return SimpleNamespace(
        message_id=message_id,
        chat_id="chat-1",
        sender_id="u1",
        channel_type="wechat",
        message_type=kind,
        content=content,
        metadata={"ingest_to_kb": True, "agent_id": "default", **(metadata or {})},
        timestamp=None,
    )


def _parsed(text="解析正文"):
    return SimpleNamespace(
        metadata={"title": "t", "page_count": 1, "ocr_used": False,
                  "ocr_engine": "", "ocr_confidence_avg": None},
        content=text,
        chunks=[{"content": text}],
        parents=[],
        doc_id="doc-1",
        ingest_time="2026-10-24T00:00:00+00:00",
        source_type="wecom",
    )


@pytest.fixture()
def bridge(tmp_path):
    queue = KnowledgeIngestQueue(str(tmp_path / "ingest_jobs.db"))
    b = KnowledgeIngestBridge(queue=queue)
    yield b
    queue.close()


def test_text_message_creates_entry_and_publishes_result(monkeypatch, bridge):
    repo = FakeRepo()
    monkeypatch.setattr(bridge_module, "get_knowledge_repository", lambda: repo)
    published = []
    monkeypatch.setattr(
        bridge_module, "get_ingest_bus",
        lambda: SimpleNamespace(publish=lambda topic, payload: published.append((topic, payload))),
    )
    monkeypatch.setattr(bridge_module, "parse_document", lambda *a, **k: _parsed())

    result = asyncio.run(bridge.ingestChannelMessage(_message(), "default"))

    assert result["status"] == "accepted"
    assert repo.created[0]["source"].startswith("wecom:")
    assert {topic for topic, _ in published} >= {"kb/ingest/wecom", "kb/ingest/result"}


def test_duplicate_message_does_not_create_twice(monkeypatch, bridge):
    repo = FakeRepo(existing={"knowledge_id": "k-old"})
    monkeypatch.setattr(bridge_module, "get_knowledge_repository", lambda: repo)
    monkeypatch.setattr(
        bridge_module, "get_ingest_bus",
        lambda: SimpleNamespace(publish=lambda *a, **k: 0),
    )

    result = asyncio.run(bridge.ingestChannelMessage(_message(), "default"))

    assert result == {"status": "duplicate", "knowledge_id": "k-old"}
    assert repo.created == []


def test_image_without_media_is_honest(monkeypatch, bridge):
    repo = FakeRepo()
    monkeypatch.setattr(bridge_module, "get_knowledge_repository", lambda: repo)
    monkeypatch.setattr(
        bridge_module, "get_ingest_bus",
        lambda: SimpleNamespace(publish=lambda *a, **k: 0),
    )

    result = asyncio.run(bridge.ingestChannelMessage(
        _message("image", content="[图片]"), "default"
    ))

    assert result["status"] == "skipped"
    assert result["reason"] == "media_unavailable"


def test_voice_uses_transcription(monkeypatch, bridge):
    repo = FakeRepo()
    monkeypatch.setattr(bridge_module, "get_knowledge_repository", lambda: repo)
    monkeypatch.setattr(
        bridge_module, "get_ingest_bus",
        lambda: SimpleNamespace(publish=lambda *a, **k: 0),
    )
    monkeypatch.setattr(bridge_module, "parse_document", lambda *a, **k: _parsed("语音转写"))

    monkeypatch.setattr(bridge, "_transcribe", lambda message: _async("语音转写"))
    result = asyncio.run(bridge.ingestChannelMessage(_message("voice", content="[语音]"), "default"))

    assert result["status"] == "accepted"
    assert repo.created[0]["content"] == "语音转写"


def test_link_is_fetched_via_safe_fetch(monkeypatch, bridge):
    repo = FakeRepo()
    monkeypatch.setattr(bridge_module, "get_knowledge_repository", lambda: repo)
    monkeypatch.setattr(
        bridge_module, "get_ingest_bus",
        lambda: SimpleNamespace(publish=lambda *a, **k: 0),
    )
    monkeypatch.setattr(bridge_module, "parse_document", lambda *a, **k: _parsed("网页正文"))

    monkeypatch.setattr(bridge, "_fetchUrl", lambda url: _async("<html>正文</html>".encode("utf-8")))
    result = asyncio.run(bridge.ingestChannelMessage(
        _message(content="请看 https://example.com/doc"), "default"
    ))

    assert result["status"] == "accepted"
    assert repo.created[0]["content"] == "网页正文"


def test_ingest_enabled_reads_channel_config():
    from neurova.knowledge.ingest_bridge import ingestEnabled

    on = SimpleNamespace(config=SimpleNamespace(extra={"ingest_to_kb": "true"}))
    off = SimpleNamespace(config=SimpleNamespace(extra={}))
    assert ingestEnabled(on) is True
    assert ingestEnabled(off) is False


def test_ingest_disabled_is_noop(monkeypatch, bridge):
    repo = FakeRepo()
    monkeypatch.setattr(bridge_module, "get_knowledge_repository", lambda: repo)
    message = _message()
    message.metadata["ingest_to_kb"] = False

    result = asyncio.run(bridge.ingestChannelMessage(message, "default"))

    assert result["status"] == "skipped"
    assert repo.created == []


async def _async(value):
    return value


def test_stats_counts_outcomes_without_faking_backlog(monkeypatch, bridge):
    repo = FakeRepo()
    monkeypatch.setattr(bridge_module, "get_knowledge_repository", lambda: repo)
    monkeypatch.setattr(
        bridge_module, "get_ingest_bus",
        lambda: SimpleNamespace(
            publish=lambda *a, **k: 0, subscriberCount=lambda *a, **k: 0
        ),
    )
    monkeypatch.setattr(bridge_module, "parse_document", lambda *a, **k: _parsed())
    asyncio.run(bridge.ingestChannelMessage(
        _message(metadata={"ingest_to_kb": False}), "default"
    ))
    asyncio.run(bridge.ingestChannelMessage(_message(), "default"))
    stats = bridge.stats()

    assert stats["skipped"] == 1
    assert stats["accepted"] == 1
    assert "backlog" not in stats
    assert stats["topics"]["kb/ingest/wecom"] == 0


def test_oversized_media_is_skipped_honestly(monkeypatch, bridge):
    repo = FakeRepo()
    monkeypatch.setattr(bridge_module, "get_knowledge_repository", lambda: repo)
    monkeypatch.setattr(
        bridge_module, "get_ingest_bus",
        lambda: SimpleNamespace(publish=lambda *a, **k: 0),
    )
    monkeypatch.setattr(bridge_module, "_MAX_MEDIA_BYTES", 4)

    result = asyncio.run(bridge.ingestChannelMessage(
        _message("file", metadata={"media_bytes": b"12345", "file_name": "big.md"}),
        "default",
    ))

    assert result == {"status": "skipped", "reason": "media_too_large"}
    assert repo.created == []


def testResidentWorkerDrainsThenStops(monkeypatch):
    from neurova.knowledge import ingest_bridge as module

    calls = {"drain": 0}
    stop = module.asyncio.Event()

    class _Fake:
        async def drainPending(self, limit=20):
            calls["drain"] += 1
            if calls["drain"] >= 2:
                stop.set()
            return [{"status": "accepted"}] if calls["drain"] == 1 else []

    monkeypatch.setattr(module, "get_ingest_bridge", lambda: _Fake())

    asyncio.run(module.runIngestWorker(intervalSeconds=0.01, stopEvent=stop))

    assert calls["drain"] >= 2
    assert stop.is_set()


class _FakeMqttClient:
    def __init__(self):
        self.on_message = None
        self.published = []

    def publish(self, topic, payload, qos=1):
        self.published.append((topic, json.loads(payload)))

    def loop_stop(self):
        pass

    def disconnect(self):
        pass


class TestMqttIngestTransport:
    def testProducerPublishesJobAndDoesNotConsumeLocally(self, tmp_path, monkeypatch):
        from neurova.knowledge.ingest_mqtt import JOB_TOPIC, MqttIngestTransport

        repo = FakeRepo()
        monkeypatch.setattr(bridge_module, "get_knowledge_repository", lambda: repo)
        queue = KnowledgeIngestQueue(str(tmp_path / "jobs.db"))
        client = _FakeMqttClient()
        transport = MqttIngestTransport(client=client)
        bridge = KnowledgeIngestBridge(queue=queue, transport=transport)

        result = asyncio.run(bridge.ingestChannelMessage(_message(), "default"))

        assert result["status"] == "published"
        assert repo.created == []
        topic, body = client.published[0]
        assert topic == JOB_TOPIC
        assert body["dedupe_key"] == "wecom:chat-1:m1"
        assert body["payload"]["tenant_id"] == "default"
        assert queue.stats()["pending"] == 0
        queue.close()

    def testConsumerWritesJobIntoLocalQueue(self, tmp_path, monkeypatch):
        from neurova.knowledge import ingest_bridge as module

        queue = KnowledgeIngestQueue(str(tmp_path / "jobs.db"))
        monkeypatch.setattr(module, "get_knowledge_ingest_queue", lambda: queue)
        body = {
            "dedupe_key": "wecom:c:mqtt-1",
            "payload": {"agent_id": "default", "tenant_id": "t1",
                        "event": {"event_id": "wecom:c:mqtt-1"},
                        "message": {"content": "x"}, "metadata": {}},
        }

        jobId = module.enqueueFromMqtt(body)

        assert jobId
        assert queue.stats()["pending"] == 1
        queue.close()


def testMqttIngestTlsConfigReachesClient():
    from neurova.knowledge.ingest_mqtt import MqttIngestTransport

    class _TlsClient(_FakeMqttClient):
        def __init__(self):
            super().__init__()
            self.tls = None
            self.insecure = False

        def tls_set(self, ca_certs=None, certfile=None, keyfile=None):
            self.tls = (ca_certs, certfile, keyfile)

        def tls_insecure_set(self, value):
            self.insecure = bool(value)

    client = _TlsClient()
    transport = MqttIngestTransport(
        client=client, tlsCa="ca.pem", tlsCert="cert.pem",
        tlsKey="key.pem", tlsInsecure=True,
    )
    transport._ensureClient()

    assert client.tls == ("ca.pem", "cert.pem", "key.pem")
    assert client.insecure is True
