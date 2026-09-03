"""neurflow 出站请求 SSRF 防护单元测试

覆盖 _validate_outbound_url 的协议白名单、解析 IP 边界判定
（私网/环回/链路本地/元数据/IPv4-mapped IPv6）、放行名单，
以及 exec_remote_api 对内网目标的拒绝行为。
"""

import socket
from unittest.mock import patch

import pytest

from neurova.collaboration.neurflow.builtin import (
    _OutboundResponse,
    _safe_request,
    _validate_outbound_url,
)


def _fake_dns(mapping):
    """构造 getaddrinfo 替身：host → [ (AF_INET, ..., (ip, port)) ]"""

    def fake_getaddrinfo(host, port, *args, **kwargs):
        ip = mapping.get(host)
        if ip is None:
            raise socket.gaierror(f"unknown host: {host}")
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 0, "", (ip, port))]

    return fake_getaddrinfo


class TestValidateOutboundUrl:
    def test_public_http_url_passes(self):
        with patch("socket.getaddrinfo", _fake_dns({"example.com": "93.184.216.34"})):
            assert _validate_outbound_url("https://example.com/search") == "https://example.com/search"

    def test_rejects_non_http_schemes(self):
        for url in ("ftp://example.com", "file:///etc/passwd", "gopher://x.com"):
            with pytest.raises(ValueError, match="不允许的协议"):
                _validate_outbound_url(url)

    def test_rejects_missing_host(self):
        with pytest.raises(ValueError, match="缺少主机名"):
            _validate_outbound_url("http:///path")

    def test_rejects_loopback_ip_literal(self):
        with pytest.raises(ValueError, match="受限地址"):
            _validate_outbound_url("http://127.0.0.1:9527/api")

    def test_rejects_private_ranges(self):
        for ip in ("10.0.0.5", "172.16.1.1", "192.168.1.100"):
            with pytest.raises(ValueError, match="受限地址"):
                _validate_outbound_url(f"http://{ip}/x")

    def test_rejects_metadata_link_local(self):
        # 云厂商元数据端点 169.254.169.254 属链路本地段
        with pytest.raises(ValueError, match="受限地址"):
            _validate_outbound_url("http://169.254.169.254/latest/meta-data")

    def test_rejects_ipv6_loopback(self):
        with pytest.raises(ValueError, match="受限地址"):
            _validate_outbound_url("http://[::1]/x")

    def test_rejects_ipv4_mapped_ipv6(self):
        with patch("socket.getaddrinfo", _fake_dns({"evil.example": "::ffff:10.0.0.8"})):
            with pytest.raises(ValueError, match="受限地址"):
                _validate_outbound_url("http://evil.example/x")

    def test_domain_resolving_to_private_rejected(self):
        with patch("socket.getaddrinfo", _fake_dns({"rebind.example": "192.168.0.7"})):
            with pytest.raises(ValueError, match="受限地址"):
                _validate_outbound_url("http://rebind.example/x")

    def test_dns_failure_rejected(self):
        with patch("socket.getaddrinfo", _fake_dns({})):
            with pytest.raises(ValueError, match="解析失败"):
                _validate_outbound_url("http://nonexistent.invalid/x")

    def test_allowlist_bypasses_resolution(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_SSRF_ALLOWLIST", "internal.lan,10.0.0.3")
        # 放行名单命中时不做解析（即使 DNS 不存在也放行）
        assert _validate_outbound_url("http://internal.lan/api").endswith("/api")
        monkeypatch.setenv("NEUROVA_SSRF_ALLOWLIST", "*")
        assert _validate_outbound_url("http://127.0.0.1/x")


class TestSafeRequestBehavior:
    @pytest.mark.asyncio
    async def test_exec_remote_api_blocks_internal_target(self):
        """远程 API 节点对内网目标必须返回 failed 且不发起请求"""
        from neurova.collaboration.neurflow.builtin import exec_remote_api

        result = await exec_remote_api(
            {"method": "GET", "url": "http://127.0.0.1:9527/admin"}, {}
        )
        assert result["status"] == "failed"
        assert "SSRF" in str(result["error"])

    def test_safe_request_rejects_bad_scheme_before_network(self):
        with pytest.raises(ValueError, match="不允许的协议"):
            _safe_request("GET", "file:///etc/passwd")

    def test_response_adapter_shape(self):
        resp = _OutboundResponse(200, b'{"ok": true}', "http://x")
        assert resp.ok is True
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        err = _OutboundResponse(500, b"boom", "http://x")
        assert err.ok is False
