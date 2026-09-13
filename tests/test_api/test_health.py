"""
健康检查端点测试

测试目标：neurova/api/endpoints/health.py
覆盖：健康检查路由、探针
"""

from pathlib import Path

import pytest
from neurova.api.endpoints.health import router


class TestHealthRouter:
    """健康检查路由（现行契约：router 裸定义 + 注册表挂载 "/v1/health"，
    探针面为 /checks 系——live/ready 随检查器重构更替）。残留处理 2026-09-13"""

    def test_mount_prefix_at_registry(self):
        src = Path("neurova/api/endpoints/__init__.py").read_text(encoding="utf-8")
        assert '"/v1/health", "Health API"' in src

    def test_router_has_routes(self):
        assert len(router.routes) > 0

    def test_checks_routes_exist(self):
        paths = {r.path for r in router.routes}
        assert "" in paths  # 根=健康状态
        assert "/checks" in paths
        assert "/checks/{name}" in paths

    def test_report_and_recover_routes_exist(self):
        paths = {r.path for r in router.routes}
        assert "/report" in paths
        assert "/recover" in paths
