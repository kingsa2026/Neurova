"""
P0-2 MCP 白名单目录（TDD）。

交付物（docs/Neurova_Agent工具扩展计划_2026-09-12.md P0-2）：
一份精选 MCP server 目录 + 安装端点，让非专家一键接上原生工具面缺失的
高星能力（github / context7 / dbhub）。计划的"官方 servers git/fetch"与
P0-3 原生 git + 已有 web_fetch 重叠，按"不镀金"剔除。

安全：build_server_config 产出的配置必须过 validate_mcp_server_config；
stdio=本机进程派生，安装端点沿用 connect 端点的 admin 门；密钥只进 env，
不写日志。本测试不实际 spawn npx/docker，只验配置构造与校验契约。
"""

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest


def _make_app_client():
    from fastapi.testclient import TestClient
    from neurova.api.app import create_app

    return TestClient(create_app())


# ═══════════════════════════════════════════════════════════════
# 目录数据契约
# ═══════════════════════════════════════════════════════════════

class TestCatalogData:
    def test_lists_curated_entries(self):
        from neurova.tool_layers.mcp_catalog import list_catalog

        ids = {e["id"] for e in list_catalog()}
        assert {"github", "context7", "dbhub"} <= ids
        # 明确剔除与原生工具重叠项
        assert not ({"git", "fetch"} & ids)

    def test_every_entry_has_required_fields(self):
        from neurova.tool_layers.mcp_catalog import list_catalog

        for e in list_catalog():
            assert e["id"] and e["name"] and e["description"]
            assert isinstance(e["required_secrets"], list)
            assert e["transport"] in ("stdio", "http", "sse")

    def test_context7_and_dbhub_use_npx(self):
        """Node 已随包捆绑 → npx 系 server 开箱可跑。"""
        from neurova.tool_layers.mcp_catalog import get_entry

        assert get_entry("context7")["command"].endswith("npx") or get_entry("context7")["command"] == "npx"
        assert get_entry("dbhub")["command"] in ("npx",) or "npx" in get_entry("dbhub")["command"]

    def test_github_requires_docker_flagged(self):
        """github-mcp-server 分发形态是 Docker 镜像 → 声明 requires，供 UI 门控。"""
        from neurova.tool_layers.mcp_catalog import get_entry

        assert get_entry("github").get("requires") == "docker"


# ═══════════════════════════════════════════════════════════════
# build_server_config：产出合法 MCP server 配置（过 validate 契约）
# ═══════════════════════════════════════════════════════════════

class TestBuildServerConfig:
    def test_github_config_valid_and_carries_token(self):
        from neurova.tool_layers.mcp_catalog import build_server_config
        from neurova.tool_layers.mcp_config import validate_mcp_server_config

        cfg = build_server_config("github", {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx"})
        normalized = validate_mcp_server_config(cfg)  # 不抛 = 合法
        assert normalized["transport"] == "stdio"
        assert normalized["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp_xxx"

    def test_missing_secret_rejected(self):
        from neurova.tool_layers.mcp_catalog import build_server_config

        with pytest.raises(ValueError):
            build_server_config("github", {})  # github 必须有 token

    def test_optional_secret_defaults_empty(self):
        from neurova.tool_layers.mcp_catalog import build_server_config
        from neurova.tool_layers.mcp_config import validate_mcp_server_config

        # context7 的 API key 可选，缺失也能构造
        cfg = build_server_config("context7", {})
        validate_mcp_server_config(cfg)

    def test_dbhub_dsn_required(self):
        from neurova.tool_layers.mcp_catalog import build_server_config

        cfg = build_server_config("dbhub", {"CONNECTION_STRING": "postgresql://u:p@h/db"})
        assert "postgresql://u:p@h/db" in " ".join(cfg["args"]) or \
               cfg["env"].get("CONNECTION_STRING") == "postgresql://u:p@h/db"
        with pytest.raises(ValueError):
            build_server_config("dbhub", {})

    def test_unknown_entry_raises(self):
        from neurova.tool_layers.mcp_catalog import build_server_config

        with pytest.raises(KeyError):
            build_server_config("no_such_server", {})

    def test_dbhub_secret_marked_read_only_required(self):
        """P1-4：只读 SQL 的诚实落点 = DSN 用只读账号（dbhub 无 --readonly CLI 标志，
        代理层正则匹配 SQL 属"安全剧场"）。目录以 read_only_required 标记该契约，
        供前端渲染强提示。"""
        from neurova.tool_layers.mcp_catalog import get_entry

        spec = next(
            s for s in get_entry("dbhub")["required_secrets"] if s["key"] == "CONNECTION_STRING"
        )
        assert spec.get("read_only_required") is True

    def test_secrets_never_leak_into_command_args(self):
        """密钥只进 env，不得出现在 args（args 会进进程列表/UI 展示）。"""
        from neurova.tool_layers.mcp_catalog import build_server_config

        cfg = build_server_config("github", {"GITHUB_PERSONAL_ACCESS_TOKEN": "SECRET123"})
        assert "SECRET123" not in " ".join(cfg.get("args", []))


# ═══════════════════════════════════════════════════════════════
# 安装端点：admin 门 + 校验 + 持久化 + 连接（不真 spawn）
# ═══════════════════════════════════════════════════════════════

class TestInstallEndpoint:
    def test_catalog_list_endpoint_requires_auth(self):
        client = _make_app_client()
        resp = client.get("/api/v1/tool-layers/mcp-catalog")
        # 路由级 get_current_user 保护：未带凭据 401
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════
# 复核补测（2026-09-12）：/test 端点闭环 + register http 传输不误判 stdio
# ═══════════════════════════════════════════════════════════════

class TestMCPEndpointContract:
    def _client_as_admin(self):
        from fastapi.testclient import TestClient
        from neurova.api.app import create_app
        from neurova.api.auth import get_current_user

        client = TestClient(create_app())
        client.app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "root", "role": "admin"
        }
        return client

    def test_test_endpoint_unknown_server_404(self):
        client = self._client_as_admin()
        resp = client.post("/api/v1/tool-layers/mcp-servers/no_such_server/test")
        assert resp.status_code == 404

    def test_register_http_url_not_rejected_as_stdio(self):
        """复核修正回归：URL 注册须按 http 传输校验，不得因 transport 默认
        stdio 而要求 command（预存 bug：手动注册恒 400）。打桩持久化+连接，
        只验传输门（不真写共享配置、不真连端口）。"""
        client = self._client_as_admin()
        mgr = Mock()
        mgr.add_mcp_server = Mock(return_value=True)
        mgr.get_mcp_server = Mock(return_value={"id": "probe_http"})
        mcp_client = Mock()
        mcp_client.connect_server = AsyncMock(return_value=False)  # 连接失败不影响传输判定
        mcp_client.get_server_status = Mock(return_value={"tool_count": 0})
        with patch("neurova.shared_config.get_shared_config_manager", return_value=mgr), \
             patch("neurova.tool_layers.mcp_client.get_mcp_client", return_value=mcp_client):
            resp = client.post(
                "/api/v1/tool-layers/mcp-servers",
                json={"name": "probe_http", "url": "http://127.0.0.1:9/mcp", "transport": "http"},
            )
        # admin + http：通过传输门，返回 MCPServerInfo（transport=http），非 400 stdio 缺 command
        assert resp.status_code == 200, resp.text
        assert resp.json().get("transport") == "http"

    def test_register_with_auth_token_headers_persisted_and_used(self):
        """复核修复回归：register 弹窗 auth_token → Authorization 头必须①持久化
        ②真实传给连接层（协议层 _open_session 消费 config.headers）。"""
        client = self._client_as_admin()
        mgr = Mock()
        mgr.add_mcp_server = Mock(return_value=True)
        mgr.get_mcp_server = Mock(return_value={"id": "authed"})
        mcp_client = Mock()
        mcp_client.connect_server = AsyncMock(return_value=True)
        mcp_client.get_server_status = Mock(return_value={"tool_count": 3})
        with patch("neurova.shared_config.get_shared_config_manager", return_value=mgr), \
             patch("neurova.tool_layers.mcp_client.get_mcp_client", return_value=mcp_client):
            resp = client.post(
                "/api/v1/tool-layers/mcp-servers",
                json={
                    "name": "authed",
                    "url": "https://mcp.example.com/sse",
                    "transport": "http",
                    "headers": {"Authorization": "Bearer tok-123"},
                },
            )
        assert resp.status_code == 200, resp.text
        # ① 持久化配置携带 Authorization 头
        persisted = mgr.add_mcp_server.call_args[0][0]
        assert persisted["headers"]["Authorization"] == "Bearer tok-123"
        # ② 连接层收到含 headers 的配置（http/sse 真实带 bearer）
        connect_cfg = mcp_client.connect_server.call_args[0][1]
        assert connect_cfg["headers"]["Authorization"] == "Bearer tok-123"
        # ③ 响应不回显 token（GET /mcp-servers 契约同理：只回元信息）
        body = resp.json()
        assert "tok-123" not in json.dumps(body, ensure_ascii=False)
        assert body["tools_count"] == 3
