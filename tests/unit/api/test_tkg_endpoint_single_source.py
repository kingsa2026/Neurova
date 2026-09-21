"""Issue #72 · 时序事实只有一份权威：API 写进去的事实必须落到被读的底座。

三条断链叠在一起（审计 `docs/specs/2026-09-21-memory-knowledge-foundation-audit.md` §B-02 / §5.3）：
1. `POST /memory/tkg/facts` 把 `entity/attribute/value` 交给只认
   `subject/predicate/obj` 的委托层 ⇒ 三个字段全取不到，**每次调用静默写一条空三元组**，
   HTTP 层还是 200；
2. 事实落在 `modules/tkg_module.py` 的进程内字典里（`_facts`）⇒ 进程一灭就没了，
   而且检索链读的是底座 `knowledge_facts`，从来不读它；
3. `POST /memory/tkg/query` 调的 `manager.tkg_query` 根本不存在 ⇒ 恒 500。

本文件锁定：一份权威（底座）、字段契约归一、坏输入响亮拒绝、读面读得到写进去的事实。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user_or_default
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.temporal_facts import TemporalFactReader

BASE = "/api/v1/memory"


@pytest.fixture()
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture()
def manager(tmp_path, store):
    m = MemoryManager(
        db_path=str(tmp_path / "mem.db"),
        agent_id="tkg-agent",
        neuser_id="neu",
        user_id="u1",
        enable_buffer=False,
    )
    m.attachFactStore(store)
    yield m
    m.close()


@pytest.fixture()
def client(manager):
    from unittest.mock import patch

    from neurova.api.error_handlers import register_error_handlers
    from neurova.api.endpoints.memory import tkg as tkgModule

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(tkgModule.router, prefix=BASE)
    app.dependency_overrides[get_current_user_or_default] = lambda: {
        "user_id": "u1",
        "neuser_id": "neu",
        "role": "user",
    }
    # 端点直接调用模块级 `get_memory_manager`（不是 Depends），所以补丁打在它的
    # 模块命名空间上——注入隔离 manager，不碰应用全局状态。
    with patch.object(tkgModule, "get_memory_manager", lambda *a, **k: manager):
        yield TestClient(app, raise_server_exceptions=False)


class TestFactsLandInTheSingleAuthority:
    def test_addedFactIsReadableFromTheFoundationStore(self, client, store, manager):
        resp = client.post("/api/v1/memory/tkg/facts", json={
            "entity": "神经瓦", "attribute": "version", "value": "2.0",
        })
        assert resp.status_code == 200, resp.text

        facts = [f for f in store.searchableFacts(agentId="tkg-agent")
                 if f["record_kind"] == "triple"]
        assert [(f["predicate_term_id"], f["object_term"]) for f in facts] == [("version", "2.0")]

        hits = TemporalFactReader(store, agentId="tkg-agent").forQuery("神经瓦 现在什么版本")
        assert [h["object"] for h in hits] == ["2.0"], "写进去的事实必须被答题读面读到"

    def test_blankSubjectsAreRejectedLoudly(self, client, store):
        """空字段不许被当成"写成功"——这就是那条静默空三元组的入口。"""
        resp = client.post("/api/v1/memory/tkg/facts", json={
            "entity": "", "attribute": "", "value": "",
        })
        assert 400 <= resp.status_code < 500, "坏输入必须以显式 4xx 暴露，不能 200 假成功"
        assert store.searchableFacts(agentId="tkg-agent") == []

    def test_queryFindsWhatWasWritten(self, client):
        """`/tkg/query` 此前恒 500（manager 上没有 tkg_query 这个动词）。"""
        client.post("/api/v1/memory/tkg/facts", json={
            "entity": "神经瓦", "attribute": "version", "value": "2.0",
        })

        resp = client.post("/api/v1/memory/tkg/query", json={"entity": "神经瓦"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["count"] == 1

    def test_statsComeFromTheAuthorityNotAPrivateDict(self, client, store):
        client.post("/api/v1/memory/tkg/facts", json={
            "entity": "神经瓦", "attribute": "version", "value": "2.0",
        })

        data = client.get("/api/v1/memory/tkg/stats").json()["data"]
        assert data["total_facts"] == 1
        assert data["entities"] == 1


class TestNoSecondFactStore:
    def test_moduleHoldsNoPrivateFactDict(self):
        """第三套内存事实库退役：模块里不许再有 `_facts` 私有字典。"""
        from neurova.cognitive_layers.memory_layer.modules.tkg_module import TKGModule

        module = TKGModule()
        assert not hasattr(module, "_facts"), "私有事实字典是第二个事实源，必须删净"
