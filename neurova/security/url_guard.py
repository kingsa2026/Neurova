from __future__ import annotations

"""
统一出网 URL 边界校验（SSRF 防护）——**全仓单源**。

审计 2026-11-16（教义第 7 条）：security/url_guard.py 与 knowledge/url_guard.py
两份同域校验并存（一份抛异常、一份回布尔，判定细节各有松紧），现收口到本模块：
knowledge 域经 `validate_public_http_url`（布尔兼容 API）走同一份判定。

能力来源：
- 本模块原有：scheme 白名单 + 显式阻断网段表 + DNS 解析逐 IP 校验 +
  fail-closed（解析失败即拒）+ allow_private 豁免；
- 自 knowledge/url_guard.py 并入：trusted_hosts 信任名单（企业内网 MCP 等
  合法内网目标）、localhost 域名快速拒绝；
- 自 neurflow builtin._validate_outbound_url 并入：IPv4-mapped IPv6 归一判定。

失败语义：`assert_public_url` 一切不合法情形抛 ValueError（fail-closed），
消息指名原因；`is_public_url` / `validate_public_http_url` 是对应布尔版。
"""

import ipaddress
import os
import socket
import urllib.parse
from dataclasses import dataclass
from typing import Optional, Iterable, Tuple

_ALLOWED_SCHEMES = ("http", "https")
SSRF_ALLOWLIST_ENV = "NEUROVA_SSRF_ALLOWLIST"

# 显式阻断网段表（刻意不含 198.18.0.0/15——Clash 等代理 fake-ip 模式的
# 标准网段，代理用户的全部域名解析都落在这里；拦截会让开代理的环境
# 完全不可用。判定层允许该段供代理配置使用；直连引擎会把对应计划标为
# directConnectable=False 并拒绝，避免把 fake-ip 当真 IP 固定）
BLOCKED_NETS = [
    ipaddress.ip_network(c)
    for c in (
        "0.0.0.0/8", "10.0.0.0/8", "127.0.0.0/8",
        "100.64.0.0/10",
        "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16",
        "192.0.0.0/24", "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24",
        "224.0.0.0/4", "::1/128", "::/128", "fc00::/7", "fe80::/10", "ff00::/8",
    )
]


def _normalizeIp(ip: ipaddress.IPv4Address | ipaddress.IPv6Address):
    """IPv4-mapped IPv6（::ffff:x.y.z.w）折算成 IPv4 再判定。"""
    if ip.version == 6 and getattr(ip, "ipv4_mapped", None):
        return ip.ipv4_mapped
    return ip


def _rejectBlockedIp(ip) -> None:
    """只按 BLOCKED_NETS 表判定——表是带例外说明的唯一口径（198.18.0.0/15
    是代理 fake-ip 标准网段，刻意不拦，见模块头注）；不再叠加 is_private
    这类宽泛属性判定，否则会把这份刻意放行一起拦掉。"""
    ip = _normalizeIp(ip)
    for net in BLOCKED_NETS:
        if ip in net:
            raise ValueError(f"目标地址被禁止（{ip} 位于 {net}）")


def configuredTrustedHosts() -> set:
    raw = os.environ.get(SSRF_ALLOWLIST_ENV) or ""
    return {entry.strip().lower() for entry in raw.split(",") if entry.strip()}


def _hostTrusted(host: str, trusted_hosts: Optional[Iterable[str]]) -> bool:
    """主机命中信任名单（精确或为某条目的子域）——命中仍要求 http/https。"""
    if not trusted_hosts:
        return False
    lowered = host.lower()
    for entry in trusted_hosts:
        entry = str(entry or "").strip().lower().lstrip(".")
        if not entry:
            continue
        if entry == "*":
            return True
        if lowered == entry or lowered.endswith("." + entry):
            return True
    return False


@dataclass(frozen=True)
class PublicUrlResolution:
    """一次校验得到的连接计划；地址集必须原样交给 HTTP 引擎，禁止二次解析。"""

    scheme: str
    host: str
    port: int
    addresses: Tuple[str, ...]
    directConnectable: bool = True


_FAKE_IP_NET = ipaddress.ip_network("198.18.0.0/15")


def _resolution(scheme: str, host: str, port: int, addresses: Tuple[str, ...]) -> PublicUrlResolution:
    directConnectable = not any(
        ipaddress.ip_address(address) in _FAKE_IP_NET for address in addresses
    )
    return PublicUrlResolution(scheme, host, port, addresses, directConnectable)


def _resolveHostAddresses(
    host: str, port: int, *, enforceBlocking: bool = True
) -> Tuple[str, ...]:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        try:
            addrInfos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as e:
            raise ValueError(f"无法解析主机名 {host}（{e}）")
        addresses = []
        for info in addrInfos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except (ValueError, IndexError):
                continue
            if enforceBlocking:
                _rejectBlockedIp(ip)
            normalized = str(_normalizeIp(ip))
            if normalized not in addresses:
                addresses.append(normalized)
        if not addresses:
            raise ValueError(f"主机名 {host} 未解析出可用 IP")
        return tuple(addresses)
    if enforceBlocking:
        _rejectBlockedIp(literal)
    return (str(_normalizeIp(literal)),)


def resolvePublicUrl(
    url: str,
    *,
    allow_private: bool = False,
    trusted_hosts: Optional[Iterable[str]] = None,
) -> PublicUrlResolution:
    """校验 URL 并返回已验证 IP 计划，供本次连接固定使用。"""
    parsed = urllib.parse.urlparse(str(url or ""))
    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"仅支持 http/https 协议（收到 {parsed.scheme or '空'}）")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("URL 缺少主机名")
    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError as e:
        raise ValueError(f"URL 端口非法: {e}")

    trusted = _hostTrusted(
        host, tuple(trusted_hosts or ()) + tuple(configuredTrustedHosts())
    )
    lowered = host.lower()
    if not trusted and (lowered == "localhost" or lowered.endswith(".localhost")):
        raise ValueError(f"目标主机被禁止（{host}）")
    if trusted or allow_private:
        try:
            addresses = _resolveHostAddresses(host, port, enforceBlocking=False)
        except ValueError:
            addresses = ()
        return _resolution(scheme, host, port, addresses)
    return _resolution(
        scheme, host, port, _resolveHostAddresses(host, port)
    )


def assert_public_url(
    url: str,
    *,
    allow_private: bool = False,
    trusted_hosts: Optional[Iterable[str]] = None,
) -> None:
    """校验出网 URL；判定与连接计划统一由 ``resolvePublicUrl`` 提供。"""
    resolvePublicUrl(url, allow_private=allow_private, trusted_hosts=trusted_hosts)


def is_public_url(
    url: str,
    *,
    allow_private: bool = False,
    trusted_hosts: Optional[Iterable[str]] = None,
) -> bool:
    """assert_public_url 的布尔版（不抛异常）"""
    try:
        assert_public_url(url, allow_private=allow_private, trusted_hosts=trusted_hosts)
    except ValueError:
        return False
    return True


def validate_public_http_url(url: str, trusted_hosts: Optional[Iterable[str]] = None) -> bool:
    """knowledge 域兼容 API（原 neurova/knowledge/url_guard.py 的入口名）。

    语义与原实现一致：不合规 → False，调用方据此拒绝；合规（含命中信任
    名单的内网目标）→ True。判定单源在 assert_public_url。
    """
    return is_public_url(url, trusted_hosts=trusted_hosts)
