"""
统一出网 URL 边界校验（P0-1 红测）

抽取自 web_reach/reach.py 的 SSRF 防护成为公共模块，供
web_reach / MCP http 配置 / P1-7 全局出网层复用。

关键契约（勿破坏）：
- 刻意不阻断 198.18.0.0/15（Clash 等代理 fake-ip 标准网段，
  拦截会让开代理环境完全不可用——见 reach.py 原注释）
"""

import pytest

from neurova.security.url_guard import assert_public_url, is_public_url


class TestSchemeCheck:
    def test_http_https_allowed(self):
        assert_public_url("http://8.8.8.8/x")
        assert_public_url("https://8.8.8.8/x")

    def test_other_schemes_rejected(self):
        with pytest.raises(ValueError, match="http"):
            assert_public_url("ftp://8.8.8.8/x")
        with pytest.raises(ValueError, match="http"):
            assert_public_url("file:///etc/passwd")

    def test_missing_host_rejected(self):
        with pytest.raises(ValueError, match="主机"):
            assert_public_url("http:///nohost")


class TestPrivateNetBlocked:
    """字面 IP 直接判定（无 DNS 依赖）"""

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:9000/mcp",
            "http://10.0.0.5/x",
            "http://192.168.1.5/x",
            "http://172.16.0.9/x",
            "http://169.254.169.254/latest/meta-data",
            "http://0.0.0.0/x",
            "http://[::1]:9000/mcp",
            "http://[fe80::1]/x",
            "http://[fc00::1]/x",
        ],
    )
    def test_private_literal_ips_blocked(self, url):
        with pytest.raises(ValueError):
            assert_public_url(url)

    def test_public_literal_ip_allowed(self):
        assert_public_url("http://8.8.8.8:9000/mcp")
        assert_public_url("http://1.1.1.1/x")


class TestFakeIpProxyRange:
    """198.18.0.0/15 代理 fake-ip 段必须放行（开代理环境的主路径）"""

    def test_fake_ip_range_allowed(self):
        assert_public_url("http://198.18.0.5/x")
        assert_public_url("http://198.19.255.255/x")


class TestHostnameResolution:
    def test_unresolvable_host_rejected(self, monkeypatch):
        # 不能依赖真实 DNS：fake-ip 代理环境（Clash）会把任何域名
        # 解析到 198.18.x.x（刻意放行段）。monkeypatch 出 gaierror
        # 测确定性的 fail-closed 路径。
        import socket

        def raise_gaierror(host, port, *a, **kw):
            raise socket.gaierror(11001, "getaddrinfo failed")

        monkeypatch.setattr(socket, "getaddrinfo", raise_gaierror)
        with pytest.raises(ValueError, match="无法解析"):
            assert_public_url("http://nonexistent.invalid/mcp")

    def test_resolved_private_ip_blocked(self, monkeypatch):
        import socket

        def fake_getaddrinfo(host, port, *a, **kw):
            return [(socket.AF_INET, None, socket.SOCK_STREAM, "", ("10.1.2.3", 0))]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        with pytest.raises(ValueError, match="10.1.2.3"):
            assert_public_url("http://internal.example.com/x")

    def test_resolved_public_ip_allowed(self, monkeypatch):
        import socket

        def fake_getaddrinfo(host, port, *a, **kw):
            return [(socket.AF_INET, None, socket.SOCK_STREAM, "", ("93.184.216.34", 0))]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        assert_public_url("http://example.com/x")


class TestAllowPrivateEscape:
    """显式 allow_private=True 跳过网段校验（系统级/管理员路径用）"""

    def test_allow_private_skips_net_check(self):
        assert assert_public_url("http://127.0.0.1:9000/mcp", allow_private=True) is None

    def test_allow_private_still_checks_scheme(self):
        with pytest.raises(ValueError, match="http"):
            assert_public_url("ftp://127.0.0.1/x", allow_private=True)


class TestBoolHelper:
    def test_is_public_url(self):
        assert is_public_url("http://8.8.8.8/x") is True
        assert is_public_url("http://127.0.0.1/x") is False
        assert is_public_url("ftp://8.8.8.8/x") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
