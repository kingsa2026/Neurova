# -*- coding: utf-8 -*-
"""P1-6 HTTP 时长/缓存命中率 + P2-7 /metrics 暴露策略（Issue #57）

P1-6：旧审计 §7 的"API 响应时长 p50/p99、吞吐量、缓存命中率"基线此前完全空白
（全仓无 HTTP 时长中间件，MemoryCache.hit_rate 从不导出）。

P2-7：`/metrics` 在全局鉴权白名单里 → 完全敞开（无鉴权/限流/来源限制）。
公开是运维抓取需求，但"公开"不等于"谁来都给"。
"""
import ast
import io
from pathlib import Path

import pytest

prometheus_client = pytest.importorskip("prometheus_client")
from prometheus_client import REGISTRY  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[3]
APIDIR = PROJECT_ROOT / "neurova" / "api"


class TestHttpMetricsMiddleware:
    def test_records_route_template_not_raw_path(self):
        """route label 必须是路由模板，否则 /items/1 与 /items/2 各成一条时间线。"""
        from starlette.testclient import TestClient

        from neurova.api.http_metrics import HttpMetricsMiddleware, UNMATCHED_ROUTE
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(HttpMetricsMiddleware)

        @app.get("/items/{item_id}")
        async def item(item_id: str):
            return {"id": item_id}

        client = TestClient(app)
        client.get("/items/1")
        client.get("/items/2")
        client.get("/no-such-route")

        assert REGISTRY.get_sample_value(
            "neurova_http_requests_total",
            {"method": "GET", "route": "/items/{item_id}", "status": "200"},
        ) == 2.0
        assert REGISTRY.get_sample_value(
            "neurova_http_requests_total",
            {"method": "GET", "route": UNMATCHED_ROUTE, "status": "404"},
        ) == 1.0

    def test_counts_unmatched_without_raw_path_label(self):
        """未匹配路由不得回落成原始 path（否则扫描器把 label 基数打爆）。"""
        src = io.open(APIDIR / "http_metrics.py", encoding="utf-8").read()
        assert 'scope.get("path")' not in src, "route label 回落原始 path（基数爆炸）"

    def test_records_duration_histogram(self):
        from starlette.testclient import TestClient

        from neurova.api.http_metrics import HttpMetricsMiddleware
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(HttpMetricsMiddleware)

        @app.get("/probe")
        async def probe():
            return {"ok": True}

        TestClient(app).get("/probe")
        labels = {"method": "GET", "route": "/probe", "status": "200"}
        assert REGISTRY.get_sample_value("neurova_http_request_seconds_count", labels) >= 1.0

    def test_middleware_registered(self):
        src = io.open(APIDIR / "middleware.py", encoding="utf-8").read()
        assert "HttpMetricsMiddleware" in src, "中间件未注册 = 指标恒空"

    def test_auth_rejections_are_measured(self, monkeypatch):
        """中间件必须覆盖被全局鉴权拒绝的请求。

        反例（实测过）：把埋点放在 GlobalAuth **内层**，enforce 模式下的 401
        根本到不了它 —— "401 洪峰"在观测面上完全空白。故它必须是最外层。
        """
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from neurova.api.middleware import setup_middleware

        monkeypatch.setenv("NEUROVA_GLOBAL_AUTH", "enforce")
        app = FastAPI()
        setup_middleware(app)

        @app.get("/api/v1/protected-probe")
        async def protected_probe():
            return {"ok": True}

        client = TestClient(app)
        assert client.get("/api/v1/protected-probe").status_code == 401

        assert REGISTRY.get_sample_value(
            "neurova_http_requests_total",
            {"method": "GET", "route": "\u005f\u005funmatched\u005f\u005f", "status": "401"},
        ) == 1.0, "401 拒绝请求未进指标（埋点被鉴权中间件短路）"

    def test_non_http_scope_passthrough(self):
        """WebSocket 等非 http scope 必须直接透传。"""
        src = io.open(APIDIR / "http_metrics.py", encoding="utf-8").read()
        assert 'scope.get("type") != "http"' in src


class TestCacheHitRateExport:
    def test_cache_registry_snapshot(self):
        from neurova.memory.core.cache import get_global_cache, iter_caches

        cache = get_global_cache()
        cache.set("k", 1)
        cache.get("k")
        names = dict(iter_caches())
        assert "memory_global" in names
        stats = names["memory_global"]
        assert {"hit_rate", "size"} <= set(stats)

    def test_observe_caches_writes_gauges(self):
        from neurova.core.metrics import get_metrics
        from neurova.memory.core.cache import get_global_cache

        cache = get_global_cache()
        cache.set("a", 1)
        cache.get("a")
        cache.get("nope")
        get_metrics().observe_caches()
        rate = REGISTRY.get_sample_value("neurova_cache_hit_rate", {"cache": "memory_global"})
        assert rate is not None and 0.0 <= rate <= 1.0

    def test_observe_caches_does_not_lazy_create(self):
        """抓指标不得创建缓存实例（否则 /metrics 本身成了消费者）。"""
        src = io.open(
            PROJECT_ROOT / "neurova" / "memory" / "core" / "cache.py", encoding="utf-8"
        ).read()
        tree = ast.parse(src)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "iter_caches":
                body = ast.get_source_segment(src, node)
                assert "get_global_cache()" not in body, "iter_caches 触发了懒建"
                assert "MemoryCache(" not in body, "iter_caches 触发了懒建"

    def test_endpoint_refreshes_caches(self):
        src = io.open(APIDIR / "app.py", encoding="utf-8").read()
        assert "observe_caches()" in src


class TestMetricsExposurePolicy:
    """P2-7：三档策略 + fail-closed 边界。"""

    def test_default_is_public(self, monkeypatch):
        from neurova.api.metrics_access import MODE_PUBLIC, get_metrics_access_mode

        monkeypatch.delenv("NEUROVA_METRICS_ACCESS", raising=False)
        assert get_metrics_access_mode() == MODE_PUBLIC

    def test_invalid_value_falls_back_public_with_warning(self, monkeypatch, caplog):
        from neurova.api.metrics_access import MODE_PUBLIC, get_metrics_access_mode

        monkeypatch.setenv("NEUROVA_METRICS_ACCESS", "bogus")
        with caplog.at_level("WARNING"):
            assert get_metrics_access_mode() == MODE_PUBLIC
        assert any("NEUROVA_METRICS_ACCESS" in r.getMessage() for r in caplog.records)

    def test_public_allows_any_source(self):
        from neurova.api.metrics_access import check_metrics_access

        allowed, _ = check_metrics_access("203.0.113.9", {})
        assert allowed is True

    def test_local_allows_loopback_only(self, monkeypatch):
        from neurova.api.metrics_access import check_metrics_access

        monkeypatch.setenv("NEUROVA_METRICS_ACCESS", "local")
        assert check_metrics_access("127.0.0.1", {})[0] is True
        assert check_metrics_access("::1", {})[0] is True
        assert check_metrics_access("203.0.113.9", {})[0] is False
        # 取不到来源 = 无法证明来源 → 拒绝（fail-closed）
        assert check_metrics_access(None, {})[0] is False

    def test_token_mode_requires_token(self, monkeypatch):
        from neurova.api.metrics_access import check_metrics_access

        monkeypatch.setenv("NEUROVA_METRICS_ACCESS", "token")
        monkeypatch.setenv("NEUROVA_METRICS_TOKEN", "s3cret")
        assert check_metrics_access(
            "203.0.113.9", {"authorization": "Bearer s3cret"}
        )[0] is True
        assert check_metrics_access("203.0.113.9", {"x-metrics-token": "s3cret"})[0] is True
        assert check_metrics_access("203.0.113.9", {"x-metrics-token": "wrong"})[0] is False
        assert check_metrics_access("203.0.113.9", {})[0] is False

    def test_token_mode_without_configured_token_fails_closed(self, monkeypatch):
        """选了 token 却没配 token：必须全拒，不得"配错就敞开"。"""
        from neurova.api.metrics_access import check_metrics_access

        monkeypatch.setenv("NEUROVA_METRICS_ACCESS", "token")
        monkeypatch.delenv("NEUROVA_METRICS_TOKEN", raising=False)
        assert check_metrics_access("127.0.0.1", {})[0] is False
        assert check_metrics_access("203.0.113.9", {"x-metrics-token": "any"})[0] is False

    def test_metrics_still_in_public_paths(self):
        """本 PR 不改全局白名单（那是既有的鉴权设计，改动面另论）。

        /metrics 的抓取门是端点内的策略判定，与"是否需要登录"是两层门。
        """
        from neurova.api.global_auth import PUBLIC_EXACT_PATHS

        assert "/metrics" in PUBLIC_EXACT_PATHS
