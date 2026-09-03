"""
测试：KBAdapter 统一知识库适配器接口（R-5 远程知识库接入）

契约:
  1. get_adapter(kb_type, config, ctx) 按 kb_type 分派：
     - local       → LocalMemoryAdapter（走 ctx["memory_manager"].search）
     - iflow       → IflowKBAdapter（心流知识库 API：startSearch/pollSearch）
     - 其他/自填   → GenericRESTAdapter（POST api_url + Bearer + dataset_id，向后兼容）
  2. 所有适配器返回统一结构 {"status": "success"|"failed", "results": [...], "error"?: str}
  3. 远程适配器 URL 必须过 SSRF 校验（localhost/私网/非 http(s) 拒绝）
  4. IflowKBAdapter 复用 iflow 协议（startSearch → pollSearch 轮询），
     网络/解析错误降级为 failed，不抛异常
"""

import os

import pytest

from neurova.knowledge.adapters import (
    FeishuKBAdapter,
    GenericRESTAdapter,
    IflowKBAdapter,
    ImaKBAdapter,
    LocalMemoryAdapter,
    get_adapter,
)

# 测试占位密钥（非真实凭据，仅验证透传逻辑）
TEST_KEY = os.environ.get("TEST_FAKE_KB_KEY", "test-placeholder-key")


class FakeMemoryManager:
    def search(self, query, limit=5):
        return [{"content": f"mem:{query}", "score": 0.9}][:limit]


class TestGetAdapter:
    def test_local_dispatch(self):
        adapter = get_adapter("local", {}, {"memory_manager": FakeMemoryManager()})
        assert isinstance(adapter, LocalMemoryAdapter)

    def test_iflow_dispatch(self):
        adapter = get_adapter("iflow", {"api_key": TEST_KEY}, {})
        assert isinstance(adapter, IflowKBAdapter)

    def test_generic_for_unknown_or_custom(self):
        # 未知 kb_type / 自定义端点向后兼容 GenericREST
        for kb_type in ("custom", "unknown_service"):
            adapter = get_adapter(kb_type, {"api_url": "https://api.example.com/search"}, {})
            assert isinstance(adapter, GenericRESTAdapter)

    def test_feishu_dispatches_to_feishu_adapter(self):
        adapter = get_adapter("feishu", {"app_id": "a", "app_secret": "s"}, {})
        assert isinstance(adapter, FeishuKBAdapter)

    def test_ima_dispatches_to_ima_adapter(self):
        adapter = get_adapter("ima", {"base_url": "http://x", "token": "t"}, {})
        assert isinstance(adapter, ImaKBAdapter)


class TestLocalMemoryAdapter:
    @pytest.mark.asyncio
    async def test_search_via_memory_manager(self):
        adapter = LocalMemoryAdapter(FakeMemoryManager())
        result = await adapter.search("hello", limit=3)
        assert result["status"] == "success"
        assert result["results"][0]["content"] == "mem:hello"

    @pytest.mark.asyncio
    async def test_missing_memory_manager_fails_gracefully(self):
        adapter = LocalMemoryAdapter(None)
        result = await adapter.search("hello", limit=3)
        assert result["status"] == "failed"
        assert "memory_manager" in result["error"]


class TestGenericRESTAdapter:
    @pytest.mark.asyncio
    async def test_rejects_insecure_url(self):
        adapter = GenericRESTAdapter(
            {"api_url": "http://localhost:9527/search", "api_key": TEST_KEY}
        )
        result = await adapter.search("q", limit=3)
        assert result["status"] == "failed"
        assert "SSRF" in result["error"] or "url" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_posts_bearer_and_dataset(self, monkeypatch):
        captured = {}

        def fake_post(url, payload, headers, timeout):
            captured["url"] = url
            captured["payload"] = payload
            captured["headers"] = headers
            return {"results": [{"id": "r1", "text": "hit"}]}

        adapter = GenericRESTAdapter(
            {
                "api_url": "https://api.example.com/search",
                "api_key": TEST_KEY,
                "dataset_id": "ds-1",
            },
            http_post=fake_post,
            validate_url=lambda u: True,
        )
        result = await adapter.search("query text", limit=5)
        assert result["status"] == "success"
        assert result["results"][0]["id"] == "r1"
        assert captured["payload"]["query"] == "query text"
        assert captured["payload"]["dataset_id"] == "ds-1"
        assert captured["payload"]["top_k"] == 5
        assert captured["headers"]["Authorization"] == f"Bearer {TEST_KEY}"

    @pytest.mark.asyncio
    async def test_network_error_fails_gracefully(self):
        def boom(url, payload, headers, timeout):
            raise ConnectionError("network down")

        adapter = GenericRESTAdapter(
            {"api_url": "https://api.example.com/search"}, http_post=boom, validate_url=lambda u: True
        )
        result = await adapter.search("q", limit=3)
        assert result["status"] == "failed"
        assert "network down" in result["error"]


class TestIflowAdapter:
    def test_default_base_url(self):
        adapter = IflowKBAdapter({"api_key": TEST_KEY})
        assert adapter.base_url == "https://platform.iflow.cn"

    @pytest.mark.asyncio
    async def test_search_polls_start_search(self, monkeypatch):
        import time as _time

        monkeypatch.setattr(_time, "sleep", lambda s: None)
        calls = {"search": 0}

        def fake_post_form(path, data, timeout):
            calls["search"] += 1
            return {"success": True, "data": {"searchId": "s-1"}}

        def fake_get(path, timeout):
            if "searchList" in path or "getSearch" in path:
                return {
                    "success": True,
                    "data": {
                        "list": [
                            {"status": "DONE", "results": [{"title": "t", "content": "c"}]}
                        ]
                    },
                }
            return {"success": True, "data": {}}

        adapter = IflowKBAdapter(
            {"api_key": TEST_KEY, "dataset_id": "kb-1", "poll_interval": 0, "poll_max": 1},
            post_form=fake_post_form,
            get=fake_get,
            validate_url=lambda u: True,
        )
        result = await adapter.search("test-query", limit=5)
        assert result["status"] == "success"
        assert result["results"], "必须返回检索结果"
        assert calls["search"] == 1

    @pytest.mark.asyncio
    async def test_insecure_base_url_rejected(self):
        adapter = IflowKBAdapter({"api_key": TEST_KEY, "base_url": "http://127.0.0.1:9000"})
        result = await adapter.search("q", limit=3)
        assert result["status"] == "failed"
