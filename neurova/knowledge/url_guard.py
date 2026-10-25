"""导入/外联 URL 的 SSRF 防护（R-4）：知识域唯一的 URL 安全校验出处。

网页导入（knowledge_ingestion）、MCP 信息源（mcp_source）等一切"按 URL 外联"
的功能都走这里——同一份判据在两处各写一份，迟早一份松一份紧。
Allowlist 语义：不合规 → False，调用方据此拒绝。
"""

from __future__ import annotations

import urllib.parse


def validate_public_http_url(url: str) -> bool:
    """校验外联 URL 安全（R-4 SSRF 防护）：
    - 仅 http/https
    - 拒绝 localhost/环回/私有/保留地址（解析后 IP 判断）
    Allowlist 语义：不合规 → False。
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname or ""
    if not host:
        return False

    # 主机名快速拒绝：localhost / 内部域名后缀
    lowered = host.lower()
    if lowered in ("localhost",) or lowered.endswith(".localhost"):
        return False

    import ipaddress

    # 直接 IP 字面量
    try:
        ip = ipaddress.ip_address(lowered)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)
    except ValueError:
        pass

    # 域名：解析后逐个 IP 检查（DNS rebinding 场景下至少列出全部分析结果）
    import socket

    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except Exception:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True
