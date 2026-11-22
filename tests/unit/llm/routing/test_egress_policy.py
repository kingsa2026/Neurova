# -*- coding: utf-8 -*-
"""R8（参照系 ad 追平批三）：LLM 出站域名策略。

契约：默认不启用（不设 NEUROVA_LLM_EGRESS_ALLOWLIST 时行为不变）；
一旦设置名单，客户端装配点对 base_url 做 fail-closed 校验——host 不在
名单（支持 *.domain 通配）即拒绝创建；解析不出 host 一律拒绝。
"""

import pytest

from neurova.llm.routing.egress_policy import (
    EgressDeniedError,
    ensureEgressAllowed,
)


class TestEgressPolicy:
    def test_no_allowlist_allows_everything(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_LLM_EGRESS_ALLOWLIST", raising=False)
        ensureEgressAllowed("https://api.example.com/v1")
        ensureEgressAllowed("http://127.0.0.1:11434")

    def test_allowlisted_host_allowed(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_LLM_EGRESS_ALLOWLIST", "api.example.com, *.corp.internal")
        ensureEgressAllowed("https://api.example.com/v1")
        ensureEgressAllowed("https://gw.corp.internal/v1")

    def test_unlisted_host_denied(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_LLM_EGRESS_ALLOWLIST", "api.example.com")
        with pytest.raises(EgressDeniedError):
            ensureEgressAllowed("https://evil.example.net/v1")

    def test_wildcard_covers_subdomain_only(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_LLM_EGRESS_ALLOWLIST", "*.corp.internal")
        ensureEgressAllowed("https://gw.corp.internal/v1")
        with pytest.raises(EgressDeniedError):
            ensureEgressAllowed("https://corp.internal/v1")  # 裸域不被 *.

    def test_unparseable_url_denied_when_allowlist_set(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_LLM_EGRESS_ALLOWLIST", "api.example.com")
        with pytest.raises(EgressDeniedError):
            ensureEgressAllowed("not-a-url")

    def test_local_models_require_explicit_allow(self, monkeypatch):
        """启用名单后，本地服务（127.0.0.1）也须显式列入——fail-closed。"""
        monkeypatch.setenv("NEUROVA_LLM_EGRESS_ALLOWLIST", "api.example.com")
        with pytest.raises(EgressDeniedError):
            ensureEgressAllowed("http://127.0.0.1:11434")
