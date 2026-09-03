"""
测试：ImaKBAdapter — 腾讯 ima 知识库适配器（R-6）

背景:
  腾讯 ima（AI 知识管家）未提供公开稳定的第三方 OpenAPI 文档；其客户端
  自 3.x 起内置 **MCP 服务**（本地/局域网 HTTP 端点 + Bearer token），
  ima 官方桌面端「设置 → 开发者 → MCP 服务」可查看端口与 Token。
  本适配器按 MCP-over-HTTP 规范对接（JSON-RPC 2.0），
  提供 tools: ima_search / ima_get_base 等知识库检索能力。

契约:
  1. base_url/token 缺失或空 → failed（优雅降级）
  2. SSRF 校验：私网地址默认拒绝（除非 validate_url 注入或 allow_local）
  3. MCP initialize → tools/list → tools/call(ima_search) 流程
  4. ima_search 返回的检索结果归一为统一 results 结构
  5. 网络/解析异常 → failed 不抛异常
"""

import pytest

from neurova.knowledge.adapters import ImaKBAdapter

TEST_TOKEN = "test-mcp-token-placeholder"


class FakeMCPTransport:
    """模拟 MCP-over-HTTP（JSON-RPC 2.0）服务端。"""

    def __init__(self):
        self.requests = []

    def post_jsonrpc(self, url, payload, headers, timeout):
        self.requests.append(payload)
        method = payload.get("method")
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "result": {
                    "serverInfo": {"name": "ima-mcp", "version": "1.0"},
                    "capabilities": {"tools": {}},
                },
            }
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "result": {
                    "tools": [
                        {"name": "ima_search", "description": "Knowledge base search"},
                        {"name": "ima_get_base", "description": "List knowledge bases"},
                    ]
                },
            }
        if method == "tools/call":
            return {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": '[{"knowledge_base":"kb1","title":"ima 索引","content":"知识库索引内容"}]',
                        }
                    ]
                },
            }
        return {"jsonrpc": "2.0", "id": payload.get("id"), "result": {}}


class TestImaAdapter:
    @pytest.mark.asyncio
    async def test_missing_credentials_fails(self):
        adapter = ImaKBAdapter({})
        result = await adapter.search("q", limit=3)
        assert result["status"] == "failed"
        assert "base_url" in result["error"] or "token" in result["error"]

    @pytest.mark.asyncio
    async def test_insecure_url_rejected(self):
        adapter = ImaKBAdapter({"base_url": "http://127.0.0.1:9007", "token": TEST_TOKEN})
        result = await adapter.search("q", limit=3)
        assert result["status"] == "failed"
        assert "校验未通过" in result["error"]

    @pytest.mark.asyncio
    async def test_allow_local_permits_loopback(self):
        """显式 allow_local=True 时放行本机 ima 服务（字面环回地址）。"""
        adapter = ImaKBAdapter(
            {"base_url": "http://127.0.0.1:9007/sse", "token": TEST_TOKEN, "allow_local": True}
        )
        assert adapter._validate_target_url("http://127.0.0.1:9007/sse") is True
        assert adapter._validate_target_url("http://localhost:9007/sse") is True

    @pytest.mark.asyncio
    async def test_allow_local_does_not_permit_public_domain(self):
        """allow_local 不放行公网域名（避免借本机白名单绕过边界）。"""
        adapter = ImaKBAdapter(
            {"base_url": "https://evil.example.com", "token": TEST_TOKEN, "allow_local": True}
        )
        # 域名（非字面 IP）不经 allow_local 放行——走公开地址校验（沙箱解析失败→拒绝）
        assert adapter._validate_target_url("https://evil.example.com/sse") is False

    @pytest.mark.asyncio
    async def test_mcp_search_roundtrip(self):
        transport = FakeMCPTransport()
        adapter = ImaKBAdapter(
            {"base_url": "http://127.0.0.1:9007/sse", "token": TEST_TOKEN},
            post_jsonrpc=transport.post_jsonrpc,
            validate_url=lambda url: True,
        )
        result = await adapter.search("知识库索引", limit=5)
        assert result["status"] == "success"
        assert len(result["results"]) >= 1
        # 确认三次 JSON-RPC 调用（initialize/tools-list/tools-call）
        methods = [r.get("method") for r in transport.requests]
        assert methods[0] == "initialize"
        assert "tools/list" in methods

    @pytest.mark.asyncio
    async def test_network_error_fails_gracefully(self):
        def boom(url, payload, headers, timeout):
            raise ConnectionError("ima unreachable")

        adapter = ImaKBAdapter(
            {"base_url": "http://127.0.0.1:9007", "token": TEST_TOKEN},
            post_jsonrpc=boom,
            validate_url=lambda url: True,
        )
        result = await adapter.search("q", limit=3)
        assert result["status"] == "failed"
        assert "unreachable" in result["error"]
