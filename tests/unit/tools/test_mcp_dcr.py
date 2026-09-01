# -*- coding: utf-8 -*-
"""
P3-b OAuth DCR（RFC 7591 动态客户端注册）防回归网

语义：oauth_config 无 client_id 但有 registration_endpoint 时，授权码流
启动前先动态注册（public client，grant_types=[authorization_code,
refresh_token]，redirect_uri=环回回调地址），注册产物（client_id 可带
client_secret）回填进 provider——无预配置 Key 也能完成首次授权。

锁定契约：
1. DCR POST registration_endpoint：软件标识 + grant_types + redirect_uri
2. 注册响应 client_id（可选 client_secret/registration_access_token）回填
3. 已有 client_id 时跳过 DCR（幂等）
4. DCR 失败 → OAuthTokenError（不静默降级到无 client_id）
5. registration_access_token 若下发则随 Authorization 头保护后续访问
"""
import pytest

from tests.unit.tools.test_mcp_oauth import _FakeTransport  # 复用桩


class _FailingTransport:
    def async_fail(self):
        pass

    async def post(self, url, data=None, headers=None):
        class R:
            status_code = 500
            text = "internal error"

            def json(self):
                return {}

        return R()


class TestDCR:
    def _cfg(self, **over):
        cfg = {
            "authorization_url": "https://idp.example.com/authorize",
            "token_url": "https://idp.example.com/token",
            "registration_endpoint": "https://idp.example.com/register",
            "scope": "mcp",
            "grant_type": "authorization_code",
        }
        cfg.update(over)
        return cfg

    def _dcr_transport(self):
        """DCR 200 → 后接 token 200 的组合桩"""
        transport = _FakeTransport([
            (200, {"client_id": "dyn-123", "client_secret": "dyn-secret",
                   "registration_access_token": "rat-1"}),
            (200, {"access_token": "ac-dyn", "expires_in": 3600}),
        ])
        return transport

    def _idp_opener(self):
        import urllib.request
        from urllib.parse import parse_qs, urlparse

        def opener(url: str) -> bool:
            qs = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
            urllib.request.urlopen(
                f"{qs['redirect_uri']}?code=dyn-code&state={qs['state']}", timeout=5
            ).read()
            return True

        return opener

    @pytest.mark.asyncio
    async def test_dcr_when_no_client_id(self, monkeypatch):
        from neurova.tool_layers.mcp_oauth import run_authorization_code_flow

        opener = self._idp_opener()
        monkeypatch.setattr("webbrowser.open", opener)
        transport = self._dcr_transport()

        cfg = self._cfg()  # 无 client_id
        token = await run_authorization_code_flow(
            "dcr-srv-1", cfg, timeout_s=10, transport=transport,
            opener=opener,
        )
        assert token == "ac-dyn"
        # DCR 请求先于 token 请求
        dcr_req = transport.requests[0]
        assert dcr_req["url"] == "https://idp.example.com/register"
        assert dcr_req["data"]["grant_types"] == ["authorization_code", "refresh_token"]
        assert dcr_req["data"]["token_endpoint_auth_method"] == "none"  # public client
        assert dcr_req["data"]["redirect_uris"]  # 环回回调地址
        # token 请求使用 DCR 下发的 client_id
        token_req = transport.requests[1]
        assert token_req["data"]["client_id"] == "dyn-123"

    @pytest.mark.asyncio
    async def test_existing_client_id_skips_dcr(self, monkeypatch):
        from neurova.tool_layers.mcp_oauth import run_authorization_code_flow

        opener = self._idp_opener()
        monkeypatch.setattr("webbrowser.open", opener)
        transport = _FakeTransport([(200, {"access_token": "ac-static", "expires_in": 3600})])

        cfg = self._cfg(client_id="static-client")
        token = await run_authorization_code_flow(
            "dcr-srv-2", cfg, timeout_s=10, transport=transport,
            opener=opener,
        )
        assert token == "ac-static"
        assert len(transport.requests) == 1  # 只有 token 请求，无 DCR
        assert transport.requests[0]["data"]["client_id"] == "static-client"

    @pytest.mark.asyncio
    async def test_dcr_failure_raises(self, monkeypatch):
        from neurova.tool_layers.mcp_oauth import OAuthTokenError, run_authorization_code_flow

        monkeypatch.setattr("webbrowser.open", lambda url: True)
        cfg = self._cfg()

        with pytest.raises(OAuthTokenError, match="动态客户端注册"):
            await run_authorization_code_flow(
                "dcr-srv-3", cfg, timeout_s=10, transport=_FailingTransport(),
                opener=lambda url: True,
            )

    @pytest.mark.asyncio
    async def test_no_client_id_and_no_registration_endpoint_raises(self):
        from neurova.tool_layers.mcp_oauth import run_authorization_code_flow

        cfg = self._cfg()
        del cfg["registration_endpoint"]
        with pytest.raises(ValueError, match="client_id"):
            await run_authorization_code_flow(
                "dcr-srv-4", cfg, timeout_s=1, transport=_FakeTransport([]),
                opener=lambda url: True,
            )

    @pytest.mark.asyncio
    async def test_registration_access_token_used_for_subsequent(self, monkeypatch):
        """DCR 下发 registration_access_token 时，token 端点请求带 Bearer 头"""
        from neurova.tool_layers.mcp_oauth import run_authorization_code_flow

        opener = self._idp_opener()
        monkeypatch.setattr("webbrowser.open", opener)
        transport = self._dcr_transport()
        await run_authorization_code_flow(
            "dcr-srv-5", self._cfg(), timeout_s=10, transport=transport,
            opener=opener,
        )
        token_headers = transport.requests[1]["headers"]
        assert token_headers.get("Authorization", "").startswith("Bearer rat-1")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
