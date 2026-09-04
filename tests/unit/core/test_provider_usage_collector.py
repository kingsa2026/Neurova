# -*- coding: utf-8 -*-
"""P1-13 provider 真账单采集器（OpenClaw provider-usage 启发）— TDD 测试

OC 语义：配额/账单从 provider 后台拉取，而非从流里抠 token（sensetime 网关
实测不回传 usage 的正解）。Neurova 落点：可选采集器框架，默认关——
- install_provider_usage_collector() 显式装配才存在（对齐工具熔断器惯例）；
- 采集器按 provider_id 注册适配函数（逐 provider 开）；
- 快照/采集结果落 provider_usage SQLite 表（含 raw JSON），失败静默；
- get_collected_usage() 供 /stats/usage-overview 扩展读取。
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.core.provider_usage import (
    ProviderUsageCollector,
    install_provider_usage_collector,
    reset_provider_usage_collector,
    uninstall_provider_usage_collector,
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_PROVIDER_USAGE_DB", str(tmp_path / "provider_usage.db"))
    reset_provider_usage_collector()
    yield
    reset_provider_usage_collector()


class TestInstallGate:
    """默认关 / 显式 install 惯例"""

    def test_not_installed_by_default(self):
        assert ProviderUsageCollector.get_installed() is None

    def test_install_then_uninstall(self):
        h = install_provider_usage_collector()
        assert ProviderUsageCollector.get_installed() is not None
        uninstall_provider_usage_collector()
        assert ProviderUsageCollector.get_installed() is None

    def test_install_idempotent(self):
        h1 = install_provider_usage_collector()
        h2 = install_provider_usage_collector()
        assert ProviderUsageCollector.get_installed() is h1


class TestProviderAdapters:
    """逐 provider 注册采集函数（适配 provider 后台 API 差异）"""

    def test_register_and_collect(self, tmp_path):
        h = install_provider_usage_collector()
        h.register_provider(
            "sensetime",
            fetch=lambda: {
                "plan": "pro",
                "quota_remaining": 12345,
                "currency": "CNY",
                "balance": 88.5,
                "window_days": 30,
                "trend": [{"date": "2026-09-04", "cost": 1.2}],
            },
        )
        h.collect_all()
        rows = h.get_collected_usage(provider_id="sensetime")
        assert len(rows) == 1
        assert rows[0]["provider_id"] == "sensetime"
        assert rows[0]["plan"] == "pro"
        assert rows[0]["quota_remaining"] == 12345

    def test_fetch_failure_recorded_not_raised(self):
        """单 provider 拉取失败静默记录，不影响其他 provider"""
        h = install_provider_usage_collector()

        def _boom():
            raise RuntimeError("backend down")

        h.register_provider("bad", fetch=_boom)
        h.register_provider("good", fetch=lambda: {"plan": "free", "quota_remaining": 1})
        h.collect_all()
        assert h.get_collected_usage(provider_id="good")
        errors = h.get_errors()
        assert any(e["provider_id"] == "bad" for e in errors)

    def test_collect_requires_installed(self):
        """未 install 时 collect_all 是 no-op（默认关）"""
        h = ProviderUsageCollector.get_installed()
        assert h is None  # 无全局实例；采集器不存在即无采集


class TestPersistence:
    """快照落 SQLite（env NEUROVA_PROVIDER_USAGE_DB 隔离）"""

    def test_snapshot_survives_reinstall(self, tmp_path):
        h = install_provider_usage_collector()
        h.register_provider("p1", fetch=lambda: {"plan": "pro", "quota_remaining": 7})
        h.collect_all()

        # 重启 = 重置 + 重装（同 env DB 路径）
        reset_provider_usage_collector()
        h2 = install_provider_usage_collector()
        rows = h2.get_collected_usage(provider_id="p1")
        assert len(rows) == 1
        assert rows[0]["quota_remaining"] == 7

    def test_get_collected_usage_empty(self):
        h = install_provider_usage_collector()
        assert h.get_collected_usage() == []
