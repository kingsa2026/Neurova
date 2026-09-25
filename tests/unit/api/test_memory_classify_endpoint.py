"""Issue #68 · `/memory/classify` 与 `/memory/classify-and-remember` 契约（红绿灯 TDD）。

端点此前**恒 500**，两处叠加根因：
1. `manager.classify_memory(request.content, request.context)` —— 两参调用一参签名 ⇒ TypeError；
2. `result["category"][0]` —— 把返回值当成 `(枚举, 置信度)` 元组，而真实返回是
   `{"memory_id","categories","tags"}` ⇒ KeyError。

端到端锁死（不 mock manager，走真实 MemoryManager）：
- 两个端点都 200 且字段与 ClassifyMemoryResponse 对齐；
- `classify-and-remember` 落库的记忆真的带分类（不是只回一个 id）；
- 分类值域 = MemoryCategory（前端页签/下拉的取值来源）。
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user_or_default
from neurova.api.endpoints.memory.eki import router
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.models import MemoryCategory

BASE = "/api/v1/memory"


@pytest.fixture()
def manager(tmp_path):
    mgr = MemoryManager(
        db_path=str(tmp_path / "mem.db"),
        agent_id="cls-api-agent",
        neuser_id="neu",
        user_id="u1",
        enable_buffer=False,
    )
    yield mgr
    mgr.close()


@pytest.fixture()
def client(manager):
    app = FastAPI()
    with patch(
        "neurova.api.endpoints.memory.eki.get_memory_manager", return_value=manager
    ):
        app.include_router(router, prefix=BASE)
        app.dependency_overrides[get_current_user_or_default] = lambda: {
            "user_id": "u1",
            "neuser_id": "neu",
            "role": "user",
        }
        yield TestClient(app)


class TestClassifyEndpoint:
    def test_classify_returns_200_not_500(self, client):
        resp = client.post(f"{BASE}/classify", json={"content": "用户喜欢深色模式"})
        assert resp.status_code == 200, f"端点恒 500 的病根未除: {resp.text}"

    def test_response_fields_match_model(self, client):
        body = client.post(
            f"{BASE}/classify", json={"content": "用户喜欢深色模式，我先把日志抓下来再汇总"}
        ).json()
        data = body["data"]
        for key in (
            "category", "category_confidence", "type", "type_confidence",
            "perspective", "perspective_confidence", "is_important",
            "is_crystallized", "confidence", "reasoning",
        ):
            assert key in data, f"响应缺字段 {key}（ClassifyMemoryResponse 契约）"
        assert isinstance(data["category"], str)
        assert isinstance(data["category_confidence"], float)

    def test_category_value_is_enum_member(self, client):
        body = client.post(
            f"{BASE}/classify", json={"content": "用户喜欢深色模式"}
        ).json()
        assert body["data"]["category"] in {c.value for c in MemoryCategory}

    def test_context_is_accepted(self, client):
        resp = client.post(
            f"{BASE}/classify",
            json={"content": "一段中性叙述", "context": {"emotion": "nostalgia"}},
        )
        assert resp.status_code == 200

    def test_classify_does_not_create_memory(self, client, manager):
        client.post(f"{BASE}/classify", json={"content": "用户喜欢深色模式"})
        assert len(manager.get_all_memories()) == 0, "分类端点是只读推断，不得落库"


class TestClassifyAndRememberEndpoint:
    def test_endpoint_returns_200(self, client):
        resp = client.post(
            f"{BASE}/classify-and-remember", json={"content": "用户喜欢深色模式"}
        )
        assert resp.status_code == 200, f"端点 500: {resp.text}"

    def test_memory_actually_carries_classification(self, client, manager):
        body = client.post(
            f"{BASE}/classify-and-remember", json={"content": "用户喜欢深色模式"}
        ).json()
        mem_id = body["data"]["memory_id"]
        mem = manager._memories[mem_id]
        assert mem.category is MemoryCategory.USER_PREFERENCE, (
            "一站式端点只回 id、分类没落到记忆行 —— 闭环断在这里"
        )

    def test_classification_block_present(self, client):
        body = client.post(
            f"{BASE}/classify-and-remember", json={"content": "用户喜欢深色模式"}
        ).json()
        block = body["data"]["classification"]
        assert block["category"] in {c.value for c in MemoryCategory}
        assert isinstance(block["categories"], list)
