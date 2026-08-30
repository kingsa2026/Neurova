from __future__ import annotations

"""
统一出网 URL 边界校验（SSRF 防护）

从 web_reach/reach.py 抽取的公共实现：scheme 白名单 + 私网/环回/链路本地
网段阻断 + DNS 解析结果逐 IP 校验。供 web_reach、MCP http 配置门
（P0-1）、后续全局出网层（P1-7）复用。

失败语义：一切不合法情形抛 ValueError（fail-closed），消息指名原因。
"""

import ipaddress
import socket
import urllib.parse

_ALLOWED_SCHEMES = ("http", "https")

# 显式阻断网段表（刻意不含 198.18.0.0/15——Clash 等代理 fake-ip 模式的
# 标准网段，代理用户的全部域名解析都落在这里；拦截会让开代理的环境
# 完全不可用。fake-ip 仅是代理内映射，实际出网由代理进程决定，不构成
# SSRF 面）
BLOCKED_NETS = [
    ipaddress.ip_network(c)
    for c in (
        "0.0.0.0/8", "10.0.0.0/8", "127.0.0.0/8",
        "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16",
        "192.0.0.0/24", "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24",
        "224.0.0.0/4", "::1/128", "::/128", "fc00::/7", "fe80::/10", "ff00::/8",
    )
]


def _reject_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    for net in BLOCKED_NETS:
        if ip in net:
            raise ValueError(f"目标地址被禁止（{ip} 位于 {net}）")


def _check_blocked_host(host: str) -> None:
    """校验主机：字面 IP 直接判定，域名走 getaddrinfo 逐解析结果判定。

    解析失败视为不通过（fail-closed）——连不上的目标本来也不可用，
    放行只会把"是否可达"的判断推迟到请求期并留下 DNS rebinding 窗口。
    """
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        _reject_blocked_ip(ip)
        return

    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise ValueError(f"无法解析主机名 {host}（{e}）")
    for info in addr_infos:
        ip = ipaddress.ip_address(info[4][0])
        _reject_blocked_ip(ip)


def assert_public_url(url: str, *, allow_private: bool = False) -> None:
    """校验出网 URL：仅 http/https，且目标主机不在私网/环回/链路本地网段。

    Args:
        url: 待校验 URL
        allow_private: 显式豁免网段校验（系统级/管理员路径用）；
            scheme 校验不受该开关影响

    Raises:
        ValueError: scheme 非法、缺少主机名、主机解析失败或命中阻断网段
    """
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"仅支持 http/https 协议（收到 {scheme or '空'}）")

    host = urllib.parse.urlparse(url).hostname
    if not host:
        raise ValueError("URL 缺少主机名")

    if allow_private:
        return

    _check_blocked_host(host)


def is_public_url(url: str, *, allow_private: bool = False) -> bool:
    """assert_public_url 的布尔版（不抛异常）"""
    try:
        assert_public_url(url, allow_private=allow_private)
    except ValueError:
        return False
    return True
