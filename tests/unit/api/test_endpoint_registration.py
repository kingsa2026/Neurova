"""
测试端点路由注册修复

验证 memory 和 tool_schema 端点正确导出 router 属性，
使 register_endpoint_routers 能够成功注册它们。
"""

import importlib
import pytest


class TestMemoryEndpointRegistration:
    """测试 memory 端点路由注册"""

    def test_memory_module_has_router(self):
        """memory 包应导出 router 属性"""
        module = importlib.import_module("neurova.api.endpoints.memory")
        assert hasattr(module, "router"), "memory 包缺少 router 属性"

    def test_memory_router_has_routes(self):
        """memory router 应包含路由"""
        module = importlib.import_module("neurova.api.endpoints.memory")
        router = module.router
        assert len(router.routes) > 0, "memory router 没有路由"

    def test_memory_stats_route_exists(self):
        """memory router 应包含 /stats/overview 路由"""
        module = importlib.import_module("neurova.api.endpoints.memory")
        router = module.router
        route_paths = [getattr(r, "path", "") for r in router.routes]
        assert any("stats" in p for p in route_paths), f"memory router 缺少 stats 路由，现有路由: {route_paths}"

    def test_memory_base_import(self):
        """从 memory.base 导入 router 应成功"""
        from neurova.api.endpoints.memory.base import router
        assert router is not None

    def test_memory_crud_imports_router(self):
        """crud 模块应能从 base 导入 router"""
        from neurova.api.endpoints.memory.crud import router as crud_router
        assert crud_router is not None


class TestToolSchemaEndpointRegistration:
    """测试 tool_schema 端点路由注册"""

    def test_tool_schema_module_importable(self):
        """tool_schema 模块应能成功导入"""
        try:
            module = importlib.import_module("neurova.api.endpoints.tool_schema")
            assert module is not None
        except Exception as e:
            pytest.fail(f"tool_schema 模块导入失败: {e}")

    def test_tool_schema_has_router(self):
        """tool_schema 模块应导出 router 属性"""
        module = importlib.import_module("neurova.api.endpoints.tool_schema")
        assert hasattr(module, "router"), "tool_schema 模块缺少 router 属性"

    def test_tool_schema_router_has_routes(self):
        """tool_schema router 应包含路由"""
        module = importlib.import_module("neurova.api.endpoints.tool_schema")
        router = module.router
        assert len(router.routes) > 0, "tool_schema router 没有路由"


class TestEndpointRegistrationIntegration:
    """测试端点注册集成"""

    def test_register_endpoint_routers_finds_memory(self):
        """register_endpoint_routers 应能找到 memory 端点"""
        module = importlib.import_module("neurova.api.endpoints.memory")
        assert hasattr(module, "router"), "memory 端点在 register_endpoint_routers 中被跳过"

    def test_register_endpoint_routers_finds_tool_schema(self):
        """register_endpoint_routers 应能找到 tool_schema 端点"""
        module = importlib.import_module("neurova.api.endpoints.tool_schema")
        assert hasattr(module, "router"), "tool_schema 端点在 register_endpoint_routers 中被跳过"
