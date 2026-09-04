# -*- coding: utf-8 -*-
"""P1-13 内置 provider 账单适配 + /stats/provider-usage 端点 — TDD 测试

锁定：
1. ProviderConfig.usage_collection 开关默认 False（默认关）且随 dict 往返保留；
2. sync_provider_usage：只采集显式开启的 provider，快照/错误隔离；
3. 内置适配按 host 匹配（deepseek/siliconflow/openrouter），未匹配 host 跳过；
4. 端点契约：登录用户返回 {snapshots, errors} 裸对象（无信封，对齐 stats 域）。
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_PROVIDER_USAGE_DB", str(tmp_path / "provider_usage.db"))
    from neurova.core.provider_usage import reset_provider_usage_collector

    # P1-13 TTL 节流（三轮断链修复①）引入模块级同步时间戳，逐测试重置
    # 保持"每次 fresh 同步"的旧测试语义
    import neurova.llm.provider_usage_adapters as _adapters

    _adapters._last_sync_at = 0.0
    reset_provider_usage_collector()
    yield
    _adapters._last_sync_at = 0.0
    reset_provider_usage_collector()


def _pc(id_, base_url, api_key="sk-test", usage_collection=True, enabled=True):
    from neurova.llm.provider_manager import ProviderConfig

    return ProviderConfig(
        id=id_,
        name=id_,
        provider="openai",
        base_url=base_url,
        api_key=api_key,
        usage_collection=usage_collection,
        enabled=enabled,
    )


class TestProviderConfigFlag:
    def test_default_off(self):
        from neurova.llm.provider_manager import ProviderConfig

        pc = ProviderConfig(id="x", name="x", provider="openai", base_url="https://a.b")
        assert pc.usage_collection is False

    def test_flag_roundtrip(self):
        from neurova.llm.provider_manager import ProviderConfig

        pc = _pc("x", "https://api.deepseek.com")
        d = pc.to_dict()
        assert d["usage_collection"] is True
        pc2 = ProviderConfig.from_dict(d)
        assert pc2.usage_collection is True


class TestSyncProviderUsage:
    def test_collects_enabled_provider(self, tmp_path):
        from neurova.llm.provider_usage_adapters import sync_provider_usage

        snap = {"plan": "pro", "quota_remaining": 100, "currency": "CNY"}
        with patch(
            "neurova.llm.provider_usage_adapters._fetch_for_provider",
            return_value=lambda: snap,
        ):
            result = sync_provider_usage([_pc("deepseek", "https://api.deepseek.com")])
        assert result["snapshots"], "应有快照"
        assert result["snapshots"][0]["provider_id"] == "deepseek"
        assert result["errors"] == []

    def test_skips_disabled_flag(self):
        """usage_collection=False 的 provider 不采集（默认关语义）"""
        from neurova.llm.provider_usage_adapters import sync_provider_usage

        result = sync_provider_usage([_pc("x", "https://api.deepseek.com", usage_collection=False)])
        assert result["snapshots"] == []
        assert result["errors"] == []

    def test_skips_no_api_key(self):
        from neurova.llm.provider_usage_adapters import sync_provider_usage

        result = sync_provider_usage([_pc("x", "https://api.deepseek.com", api_key="")])
        assert result["snapshots"] == []

    def test_unknown_host_recorded_as_error(self):
        """开启采集但无内置适配的 host：记录错误而非崩"""
        from neurova.llm.provider_usage_adapters import sync_provider_usage

        result = sync_provider_usage([_pc("weird", "https://weird.example.com")])
        assert result["snapshots"] == []
        assert any(e["provider_id"] == "weird" for e in result["errors"])

    def test_http_failure_isolated(self):
        """适配拉取失败 → 进 errors，不抛异常"""
        from neurova.llm.provider_usage_adapters import sync_provider_usage

        def _boom(p):
            raise RuntimeError("network down")

        with patch(
            "neurova.llm.provider_usage_adapters._fetch_for_provider",
            return_value=_boom,
        ):
            result = sync_provider_usage([_pc("deepseek", "https://api.deepseek.com")])
        assert result["snapshots"] == []
        assert any(e["provider_id"] == "deepseek" for e in result["errors"])
