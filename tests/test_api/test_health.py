"""
健康检查端点测试

测试目标：neurova/api/endpoints/health.py
覆盖：健康检查路由、探针
"""

import pytest
from neurova.api.endpoints.health import router


class TestHealthRouter:
    """健康检查路由"""

    def test_router_prefix(self):
        assert router.prefix == "/health"

    def test_router_tags(self):
        assert router.tags == ["健康检查"]

    def test_router_has_routes(self):
        assert len(router.routes) > 0

    def test_liveness_probe_route_exists(self):
        paths = [r.path for r in router.routes]
        assert "/health/live" in paths

    def test_readiness_probe_route_exists(self):
        paths = [r.path for r in router.routes]
        assert "/health/ready" in paths

    def test_health_status_route_exists(self):
        paths = [r.path for r in router.routes]
        assert "/health" in paths
