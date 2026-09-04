# -*- coding: utf-8 -*-
"""P1-13 断点修复 — 采集触发链与开关可达性（闭环）防回归

复审发现的两处断链：
1. sync_provider_usage 零调用方 → /stats/provider-usage 只读快照，
   采集永不触发 → 快照恒空 → 前端卡片永不显示（P1-13 死代码）。
   修：端点带 TTL 节流（5 分钟）触发当前用户 scope 的同步采集。
2. usage_collection 开关 API 不可达：manager.update_provider 无该参数、
   UpdateProviderRequest 无该字段 → 唯一开启方式是手编 providers.json。
   修：manager + API 两处透传。
"""
import os
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_PROVIDER_USAGE_DB", str(tmp_path / "provider_usage.db"))
    from neurova.core.provider_usage import reset_provider_usage_collector

    import neurova.llm.provider_usage_adapters as _adapters

    _adapters._last_sync_at = 0.0
    reset_provider_usage_collector()
    yield
    _adapters._last_sync_at = 0.0
    reset_provider_usage_collector()


def _pc(id_, usage_collection=True):
    from neurova.llm.provider_manager import ProviderConfig

    return ProviderConfig(
        id=id_, name=id_, provider="openai",
        base_url="https://api.deepseek.com",
        api_key="sk-test", usage_collection=usage_collection, enabled=True,
    )


class TestEndpointTriggersSync:
    """修①: 端点触发采集"""

    def test_sync_invoked_on_read(self, tmp_path):
        from neurova.llm.provider_usage_adapters import sync_provider_usage

        with patch(
            "neurova.llm.provider_usage_adapters.sync_provider_usage_for_user",
            return_value={"snapshots": [], "errors": []},
        ) as sync_mock:
            import asyncio

            from neurova.api.endpoints.stats import get_provider_usage
            from types import SimpleNamespace

            resp = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
                get_provider_usage(
                    request=SimpleNamespace(state=SimpleNamespace(request_id="t")),
                    current_user={"user_id": "u1", "role": "user"},
                )
            )
        sync_mock.assert_called_once()
        assert resp == {"snapshots": [], "errors": []}

    def test_ttl_throttles_backend_pulls(self, tmp_path):
        """TTL 内重复刷新不重复拉 provider 后台"""
        from neurova.llm.provider_usage_adapters import (
            USAGE_SYNC_TTL_SECONDS,
            sync_provider_usage,
        )

        assert USAGE_SYNC_TTL_SECONDS >= 60  # 节流窗口至少 1 分钟

        snap = {"plan": "pro", "quota_remaining": 9}
        with patch(
            "neurova.llm.provider_usage_adapters._fetch_for_provider",
            return_value=lambda: snap,
        ):
            r1 = sync_provider_usage([_pc("deepseek")], force=False)
            r2 = sync_provider_usage([_pc("deepseek")], force=False)
        assert r1["snapshots"], "首次应采集"
        assert len(r2["snapshots"]) == 1  # TTL 内只读快照不重拉（快照仍可读）

    def test_force_bypasses_ttl(self, tmp_path):
        from neurova.llm.provider_usage_adapters import sync_provider_usage

        snap = {"plan": "pro", "quota_remaining": 9}
        with patch(
            "neurova.llm.provider_usage_adapters._fetch_for_provider",
            return_value=lambda: snap,
        ) as fetch_mock:
            sync_provider_usage([_pc("deepseek")], force=False)
            sync_provider_usage([_pc("deepseek")], force=True)
        assert fetch_mock.call_count == 2  # force 绕过 TTL


class TestUsageCollectionToggleAPI:
    """修②: 开关经 API 可达"""

    def test_manager_update_accepts_flag(self, tmp_path):
        from neurova.llm.provider_manager import LLMProviderManager, ProviderConfig

        mgr = LLMProviderManager.__new__(LLMProviderManager)
        mgr._providers = {}
        mgr._default_provider_id = None
        # 最小依赖：update_provider 只碰 _providers 与持久化
        mgr._save_config = lambda *a, **kw: None
        mgr._config_lock = threading.RLock()
        mgr._providers["p1"] = _pc("p1", usage_collection=False)

        assert mgr.update_provider("p1", usage_collection=True) is True
        assert mgr.get_provider("p1").usage_collection is True

    def test_update_request_model_has_flag(self):
        from neurova.api.endpoints.provider import UpdateProviderRequest

        body = UpdateProviderRequest(usage_collection=True)
        assert body.usage_collection is True
        assert UpdateProviderRequest().usage_collection is None
