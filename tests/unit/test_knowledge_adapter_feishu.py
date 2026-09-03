"""
测试：FeishuKBAdapter — 飞书知识库（Wiki/云文档）适配器（R-6）

对齐飞书开放平台官方 API:
- token:   POST /open-apis/auth/v3/tenant_access_token/internal (app_id/app_secret)
- 知识空间: GET /open-apis/wiki/v2/spaces
- 文档搜索: POST /open-apis/suite/docs-api/search/doc  (query/doc_types/folder_tokens)
- 正文获取: GET /open-apis/docx/v1/documents/{id}/raw_content

契约:
  1. 无 app_id/app_secret 或未提供(use_env_env=false) → failed（优雅降级）
  2. token 缓存（expire 内复用）
  3. search() 先列空间后按空格搜索文档；无空间 → 空结果 success
  4. SSRF 校验：base_url 为私网 → failed
  5. 网络/解析错误 → failed 不抛异常
"""

import os
import time

import pytest

from neurova.knowledge.adapters import FeishuKBAdapter

TEST_APP_ID = os.environ.get("TEST_FAKE_APP_ID", "cli_test_placeholder")
TEST_APP_SECRET = os.environ.get("TEST_FAKE_APP_SECRET", "secret-placeholder")


class _FakeFeishuTransport:
    """可注入的网络交互模拟。"""

    def __init__(self):
        self.token_calls = 0
        self.search_calls = 0

    def raw_call(self, method, path, token=None, json_body=None, timeout=None):
        """返回 (status, body)。"""
        if path == "/open-apis/auth/v3/tenant_access_token/internal":
            self.token_calls += 1
            return 200, {
                "code": 0,
                "tenant_access_token": "t-123",
                "expire": 7200,
            }
        if path.startswith("/open-apis/wiki/v2/spaces") and method == "GET":
            return 200, {
                "code": 0,
                "items": [
                    {"space_id": "sp-1", "name": "团队知识库", "space_type": "team"},
                ],
            }
        if path == "/open-apis/suite/docs-api/search/doc" and method == "POST":
            self.search_calls += 1
            return 200, {
                "code": 0,
                "docs": [
                    {"obj_token": "doc-1", "title": "搜索命中文档", "doc_type": "docx"},
                ],
            }
        return 200, {"code": 0}


class TestFeishuAdapterBasics:
    @pytest.mark.asyncio
    async def test_missing_credentials_fails(self):
        adapter = FeishuKBAdapter({})
        result = await adapter.search("query", limit=3)
        assert result["status"] == "failed"
        assert "app_id" in result["error"] or "app_secret" in result["error"]

    @pytest.mark.asyncio
    async def test_insecure_base_url_rejected(self):
        adapter = FeishuKBAdapter(
            {"app_id": TEST_APP_ID, "app_secret": TEST_APP_SECRET, "base_url": "http://192.168.1.1"}
        )
        result = await adapter.search("q", limit=3)
        assert result["status"] == "failed"
        assert "SSRF" in result["error"]


class TestFeishuAdapterSearch:
    @pytest.mark.asyncio
    async def test_search_lists_spaces_then_searches(self):
        transport = _FakeFeishuTransport()
        adapter = FeishuKBAdapter(
            {
                "app_id": TEST_APP_ID,
                "app_secret": TEST_APP_SECRET,
                "space_id": None,  # 自动列出全部空间
            },
            raw_call=transport.raw_call,
            validate_url=lambda url: True,
        )
        result = await adapter.search("项目部署", limit=5)
        assert result["status"] == "success"
        assert result["results"][0]["obj_token"] == "doc-1"
        # token 获取一次、空间列表一次、搜索一次
        assert transport.token_calls == 1
        assert transport.search_calls == 1

    @pytest.mark.asyncio
    async def test_token_reused_within_expiry(self):
        transport = _FakeFeishuTransport()
        adapter = FeishuKBAdapter(
            {"app_id": TEST_APP_ID, "app_secret": TEST_APP_SECRET},
            raw_call=transport.raw_call,
            validate_url=lambda url: True,
        )
        await adapter._ensure_token()
        await adapter._ensure_token()
        assert transport.token_calls == 1, "token 应缓存复用"

    @pytest.mark.asyncio
    async def test_space_id_targets_single_space(self):
        transport = _FakeFeishuTransport()
        adapter = FeishuKBAdapter(
            {"app_id": TEST_APP_ID, "app_secret": TEST_APP_SECRET, "space_id": "sp-1"},
            raw_call=transport.raw_call,
            validate_url=lambda url: True,
        )
        result = await adapter.search("文档", limit=3)
        assert result["status"] == "success"
        # 指定 space_id 时不调空间列表（直接搜索）
        assert transport.search_calls == 1

    @pytest.mark.asyncio
    async def test_empty_spaces_returns_empty_success(self):
        transport = _FakeFeishuTransport()

        def fake_call(method, path, token=None, json_body=None, timeout=None):
            if path == "/open-apis/auth/v3/tenant_access_token/internal":
                return 200, {"code": 0, "tenant_access_token": "t", "expire": 7200}
            if path == "/open-apis/wiki/v2/spaces":
                return 200, {"code": 0, "items": []}
            return 200, {"code": 0, "docs": []}

        adapter = FeishuKBAdapter(
            {"app_id": TEST_APP_ID, "app_secret": TEST_APP_SECRET},
            raw_call=fake_call,
            validate_url=lambda url: True,
        )
        result = await adapter.search("q", limit=3)
        assert result["status"] == "success"
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_network_error_fails_gracefully(self):
        def boom(method, path, token=None, json_body=None, timeout=None):
            raise ConnectionError("feishu network down")

        adapter = FeishuKBAdapter(
            {"app_id": TEST_APP_ID, "app_secret": TEST_APP_SECRET},
            raw_call=boom,
            validate_url=lambda url: True,
        )
        result = await adapter.search("q", limit=3)
        assert result["status"] == "failed"
        assert "network down" in result["error"]
