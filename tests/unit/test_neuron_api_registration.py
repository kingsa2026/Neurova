"""
NEURON API 路由注册测试

验证 neuron.py 的 router 已正确注册到 FastAPI 应用中，
前端 /api/neuron/* 请求能被正确路由到后端端点。
"""

import pytest
from fastapi import FastAPI


class TestNeuronAPIRegistration:
    """NEURON API 路由注册验证"""

    def test_neuron_module_importable(self):
        """neuron.py 端点模块可以成功导入"""
        from neurova.api.endpoints import neuron
        assert hasattr(neuron, "router")
        assert neuron.router.prefix == "/neuron"

    def test_neuron_in_endpoint_modules(self):
        """neuron 端点在 endpoint_modules 注册列表中"""
        import inspect
        from neurova.api.endpoints import register_endpoint_routers

        source = inspect.getsource(register_endpoint_routers)
        assert "neurova.api.endpoints.neuron" in source

    def test_neuron_routes_registered_to_app(self):
        """注册后所有 NEURON 路由出现在 FastAPI app 的 routes 中"""
        app = FastAPI()
        from neurova.api.endpoints import register_endpoint_routers
        register_endpoint_routers(app)

        route_paths = {r.path for r in app.routes}

        expected_prefix = "/api/neuron"
        expected_endpoints = [
            f"{expected_prefix}/entities",
            f"{expected_prefix}/dependencies",
            f"{expected_prefix}/dependencies/{{entity_id}}",
            f"{expected_prefix}/cascade",
            f"{expected_prefix}/would-affect",
            f"{expected_prefix}/absence/detect",
            f"{expected_prefix}/extract",
            f"{expected_prefix}/stats",
            f"{expected_prefix}/health",
        ]

        for ep in expected_endpoints:
            assert ep in route_paths, f"Missing route: {ep}"

    def test_neuron_routes_match_frontend_base_url(self):
        """路由路径匹配前端 neuron.ts 的 baseURL '/api/neuron'"""
        app = FastAPI()
        from neurova.api.endpoints import register_endpoint_routers
        register_endpoint_routers(app)

        neuron_routes = [r.path for r in app.routes if "/api/neuron" in r.path]

        # 前端调用的关键端点
        assert "/api/neuron/entities" in neuron_routes
        assert "/api/neuron/stats" in neuron_routes
        assert "/api/neuron/health" in neuron_routes

    def test_neuron_routes_count(self):
        """NEURON 路由数量正确（9 个端点 × 2 HTTP methods for entities）"""
        app = FastAPI()
        from neurova.api.endpoints import register_endpoint_routers
        register_endpoint_routers(app)

        neuron_routes = [r for r in app.routes if "/api/neuron" in getattr(r, "path", "")]
        # GET /entities, POST /entities, POST /dependencies,
        # GET /dependencies/{id}, POST /cascade, POST /would-affect,
        # POST /absence/detect, POST /extract, GET /stats, GET /health
        assert len(neuron_routes) >= 9, f"Expected >=9 neuron routes, got {len(neuron_routes)}"

    def test_no_duplicate_neuron_prefix(self):
        """注册前缀为空字符串，避免与 router prefix 重复形成 /api/neuron/neuron"""
        app = FastAPI()
        from neurova.api.endpoints import register_endpoint_routers
        register_endpoint_routers(app)

        neuron_routes = [r.path for r in app.routes if "neuron" in getattr(r, "path", "")]
        for path in neuron_routes:
            assert "/neuron/neuron" not in path, f"Double prefix detected: {path}"
