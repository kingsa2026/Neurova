# -*- coding: utf-8 -*-
"""LLM 出站域名策略（R8，参照系 ad 追平批三）。

默认不启用：不设 ``NEUROVA_LLM_EGRESS_ALLOWLIST`` 时行为与历史一致
（本地模型 localhost/127.0.0.1 与任意公网服务商均可）。
启用后 fail-closed：客户端装配点对 base_url 做 host 校验，不在名单
（支持 ``*.domain`` 通配，仅匹配子域不含裸域）或解析不出 host 一律拒绝。
名单为逗号分隔的 host/通配，经部署环境变量配置（管理端运维项）。
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

_ENV = "NEUROVA_LLM_EGRESS_ALLOWLIST"


class EgressDeniedError(RuntimeError):
    """出站目标不在允许名单（启用名单后的 fail-closed 拒绝）。"""


def _allowlistHosts() -> list:
    raw = os.environ.get(_ENV, "")
    return [h.strip().lower() for h in raw.split(",") if h.strip()]


def _hostAllowed(host: str, allowlist: list) -> bool:
    host = host.lower()
    for entry in allowlist:
        if entry.startswith("*."):
            # 标准通配语义：仅匹配子域，不含裸域
            if host.endswith("." + entry[2:]):
                return True
        elif host == entry:
            return True
    return False


def ensureEgressAllowed(base_url: str) -> None:
    """校验 base_url 是否允许出站；不允许则抛 EgressDeniedError。"""
    allowlist = _allowlistHosts()
    if not allowlist:
        return
    host = urlparse(base_url).hostname or ""
    if not host or not _hostAllowed(host, allowlist):
        raise EgressDeniedError(
            f"出站目标不在允许名单：{base_url!r}（{_ENV}）"
        )
