"""聊天知识检索必须消费当前用户的 active 远程 KB 配置。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter


class RemoteStorage:
    def __init__(self):
        self.readUsers = []

    def get_configs_by_user(self, user_id):
        self.readUsers.append(user_id)
        if user_id != "u1":
            return []
        return [{
            "id": "remote-1",
            "user_id": "u1",
            "name": "团队手册",
            "source_type": "custom",
            "is_active": True,
            "settings": {"base_url": "https://kb.invalid"},
        }]

    def decrypt_api_key(self, config_id):
        return None


class RemoteAdapter:
    kb_id = "remote-1"
    name = "团队手册"
    description = "团队知识"

    def __init__(self):
        self.search = AsyncMock(return_value={
            "success": True,
            "results": [{"text": "远程部署步骤", "title": "部署", "score": 0.8}],
        })


@pytest.fixture
def remoteWiring(monkeypatch):
    storage = RemoteStorage()
    adapter = RemoteAdapter()
    monkeypatch.setattr(
        "neurova.knowledge.storage.get_knowledge_storage", lambda: storage
    )
    monkeypatch.setattr(
        "neurova.knowledge.adapters.get_adapter", lambda source, settings: adapter
    )
    monkeypatch.setattr(
        "neurova.knowledge.hybrid.hybrid_search_knowledge", lambda *args, **kwargs: []
    )
    return storage, adapter


def _context(user_id, limit=3):
    return SimpleNamespace(
        user_id=user_id,
        query="如何部署",
        limit=limit,
        metadata={"agent_id": "a1"},
    )


def testActiveRemoteKbFillsEmptyLocalResult(remoteWiring):
    storage, adapter = remoteWiring
    result = asyncio.run(KnowledgeRetrieverAdapter(object()).retrieve(_context("u1")))

    assert storage.readUsers == ["u1"]
    adapter.search.assert_awaited_once_with("如何部署", limit=3)
    assert result.metadata["hits"] == 1
    assert result.metadata["remote_kb_ids"] == ["remote-1"]
    assert result.memories[0]["content"] == "远程部署步骤"
    assert result.memories[0]["kb_id"] == "remote-1"
    assert result.memories[0]["origin"] == "untrusted"


def testAnonymousRequestNeverReadsRemoteConfigs(remoteWiring):
    storage, adapter = remoteWiring
    result = asyncio.run(KnowledgeRetrieverAdapter(object()).retrieve(_context(None)))

    assert result.memories == []
    assert storage.readUsers == []
    adapter.search.assert_not_awaited()


def testRemoteConfigsAreScopedToSender(remoteWiring):
    storage, adapter = remoteWiring
    result = asyncio.run(KnowledgeRetrieverAdapter(object()).retrieve(_context("u2")))

    assert storage.readUsers == ["u2"]
    assert result.memories == []
    adapter.search.assert_not_awaited()


def testRemoteOnlyFillsRemainingSlots(remoteWiring, monkeypatch):
    _, adapter = remoteWiring
    local = [{
        "knowledge_id": "local-1",
        "content": "本地部署说明",
        "title": "本地",
        "score": 0.9,
    }]
    monkeypatch.setattr(
        "neurova.knowledge.hybrid.hybrid_search_knowledge",
        lambda *args, **kwargs: local,
    )
    result = asyncio.run(
        KnowledgeRetrieverAdapter(object()).retrieve(_context("u1", limit=1))
    )

    assert [item["content"] for item in result.memories] == ["本地部署说明"]
    adapter.search.assert_not_awaited()
