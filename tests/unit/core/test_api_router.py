"""
API路由器测试
测试 APIRouter 的各种功能，包括端点注册、注销、查询等。
"""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from neurova.core.api_router import (
    APIRouter,
    APIEndpoint
)


class TestAPIEndpoint:
    """测试API端点"""

    def test_create_api_endpoint(self):
        """测试创建API端点"""
        def handler():
            return "OK"
        
        endpoint = APIEndpoint(
            name="test_endpoint",
            path="/api/test",
            methods=["GET", "POST"],
            handler=handler,
            auth_required=True,
            permissions=["admin"],
            metadata={"version": "1.0"}
        )
        
        assert endpoint.name == "test_endpoint"
        assert endpoint.path == "/api/test"
        assert endpoint.methods == ["GET", "POST"]
        assert endpoint.handler == handler
        assert endpoint.auth_required is True
        assert endpoint.permissions == ["admin"]
        assert endpoint.metadata == {"version": "1.0"}
        assert endpoint.plugin_id is None

    def test_api_endpoint_with_plugin_id(self):
        """测试带插件ID的端点"""
        def handler():
            return "OK"
        
        endpoint = APIEndpoint(
            name="plugin_endpoint",
            path="/api/plugin",
            methods=["POST"],
            handler=handler,
            plugin_id="plugin-123"
        )
        
        assert endpoint.plugin_id == "plugin-123"


class TestAPIRouter:
    """测试API路由器"""

    @pytest.fixture
    def router(self):
        """创建API路由器实例"""
        return APIRouter()

    @pytest.fixture
    def mock_handler(self):
        """创建模拟处理器"""
        def handler():
            return "OK"
        return handler

    def test_init(self, router):
        """测试初始化"""
        assert router is not None
        assert len(router._endpoints) == 0

    def test_register_endpoint(self, router, mock_handler):
        """测试注册端点"""
        endpoint = APIEndpoint(
            name="test_endpoint",
            path="/api/test",
            methods=["GET"],
            handler=mock_handler
        )
        
        result = router.register_endpoint(endpoint)
        assert result is True
        assert len(router._endpoints) == 1
        assert "test_endpoint" in router._endpoints

    def test_register_duplicate_endpoint(self, router, mock_handler):
        """测试注册重复端点"""
        endpoint = APIEndpoint(
            name="test_endpoint",
            path="/api/test",
            methods=["GET"],
            handler=mock_handler
        )
        
        result1 = router.register_endpoint(endpoint)
        result2 = router.register_endpoint(endpoint)
        
        assert result1 is True
        assert result2 is False
        assert len(router._endpoints) == 1

    def test_unregister_endpoint(self, router, mock_handler):
        """测试注销端点"""
        endpoint = APIEndpoint(
            name="test_endpoint",
            path="/api/test",
            methods=["GET"],
            handler=mock_handler
        )
        
        router.register_endpoint(endpoint)
        result = router.unregister_endpoint("test_endpoint")
        
        assert result is True
        assert len(router._endpoints) == 0

    def test_unregister_nonexistent_endpoint(self, router):
        """测试注销不存在的端点"""
        result = router.unregister_endpoint("non-existent")
        assert result is False

    def test_unregister_plugin_endpoints(self, router, mock_handler):
        """测试注销插件的所有端点"""
        endpoint1 = APIEndpoint(
            name="endpoint1",
            path="/api/plugin1",
            methods=["GET"],
            handler=mock_handler,
            plugin_id="plugin-123"
        )
        
        endpoint2 = APIEndpoint(
            name="endpoint2",
            path="/api/plugin2",
            methods=["POST"],
            handler=mock_handler,
            plugin_id="plugin-123"
        )
        
        endpoint3 = APIEndpoint(
            name="endpoint3",
            path="/api/other",
            methods=["GET"],
            handler=mock_handler,
            plugin_id="plugin-456"
        )
        
        router.register_endpoint(endpoint1)
        router.register_endpoint(endpoint2)
        router.register_endpoint(endpoint3)
        
        removed = router.unregister_plugin_endpoints("plugin-123")
        
        assert removed == 2
        assert len(router._endpoints) == 1
        assert "endpoint3" in router._endpoints

    def test_get_endpoint(self, router, mock_handler):
        """测试获取端点"""
        endpoint = APIEndpoint(
            name="test_endpoint",
            path="/api/test",
            methods=["GET"],
            handler=mock_handler
        )
        
        router.register_endpoint(endpoint)
        retrieved = router.get_endpoint("test_endpoint")
        
        assert retrieved is not None
        assert retrieved.name == "test_endpoint"
        assert retrieved.path == "/api/test"

    def test_get_nonexistent_endpoint(self, router):
        """测试获取不存在的端点"""
        endpoint = router.get_endpoint("non-existent")
        assert endpoint is None

    def test_get_endpoints(self, router, mock_handler):
        """测试获取所有端点"""
        for i in range(3):
            endpoint = APIEndpoint(
                name=f"endpoint{i}",
                path=f"/api/endpoint{i}",
                methods=["GET"],
                handler=mock_handler
            )
            router.register_endpoint(endpoint)
        
        endpoints = router.get_endpoints()
        assert len(endpoints) == 3

    def test_get_endpoints_by_plugin(self, router, mock_handler):
        """测试获取插件的所有端点"""
        for i in range(2):
            endpoint = APIEndpoint(
                name=f"plugin_endpoint{i}",
                path=f"/api/plugin{i}",
                methods=["GET"],
                handler=mock_handler,
                plugin_id="plugin-123"
            )
            router.register_endpoint(endpoint)
        
        endpoint = APIEndpoint(
            name="other_endpoint",
            path="/api/other",
            methods=["GET"],
            handler=mock_handler,
            plugin_id="plugin-456"
        )
        router.register_endpoint(endpoint)
        
        endpoints = router.get_endpoints_by_plugin("plugin-123")
        assert len(endpoints) == 2

    def test_get_openapi_spec(self, router, mock_handler):
        """测试生成OpenAPI规范"""
        endpoint1 = APIEndpoint(
            name="get_user",
            path="/api/users",
            methods=["GET"],
            handler=mock_handler,
            metadata={"summary": "Get users"}
        )
        
        endpoint2 = APIEndpoint(
            name="create_user",
            path="/api/users",
            methods=["POST"],
            handler=mock_handler,
            metadata={"summary": "Create user"}
        )
        
        router.register_endpoint(endpoint1)
        router.register_endpoint(endpoint2)
        
        spec = router.get_openapi_spec()
        
        assert spec['openapi'] == '3.0.0'
        assert 'info' in spec
        assert spec['info']['title'] == 'Neurova Plugin API'
        assert '/api/users' in spec['paths']
        assert 'get' in spec['paths']['/api/users']
        assert 'post' in spec['paths']['/api/users']


class TestEdgeCases:
    """测试边界情况"""

    def test_register_endpoint_empty_name(self, router, mock_handler):
        """测试注册空名称端点"""
        endpoint = APIEndpoint(
            name="",
            path="/api/test",
            methods=["GET"],
            handler=mock_handler
        )
        result = router.register_endpoint(endpoint)
        assert result is True

    def test_register_endpoint_multiple_methods(self, router, mock_handler):
        """测试注册多方法端点"""
        endpoint = APIEndpoint(
            name="multi_method",
            path="/api/multi",
            methods=["GET", "POST", "PUT", "DELETE"],
            handler=mock_handler
        )
        
        result = router.register_endpoint(endpoint)
        assert result is True
        
        retrieved = router.get_endpoint("multi_method")
        assert len(retrieved.methods) == 4

    def test_unregister_plugin_with_no_endpoints(self, router):
        """测试注销无端点的插件"""
        removed = router.unregister_plugin_endpoints("non-existent-plugin")
        assert removed == 0

    def test_openapi_spec_empty_router(self, router):
        """测试空路由器的OpenAPI规范"""
        spec = router.get_openapi_spec()
        assert spec['openapi'] == '3.0.0'
        assert len(spec['paths']) == 0

    def test_openapi_spec_with_tags(self, router, mock_handler):
        """测试带标签的OpenAPI规范"""
        endpoint = APIEndpoint(
            name="tagged_endpoint",
            path="/api/tagged",
            methods=["GET"],
            handler=mock_handler,
            metadata={"tags": ["admin", "users"]}
        )
        
        router.register_endpoint(endpoint)
        spec = router.get_openapi_spec()
        
        path_spec = spec['paths']['/api/tagged']['get']
        assert 'admin' in path_spec['tags']
        assert 'users' in path_spec['tags']

    def test_get_endpoints_by_nonexistent_plugin(self, router, mock_handler):
        """测试获取不存在的插件端点"""
        endpoint = APIEndpoint(
            name="test",
            path="/api/test",
            methods=["GET"],
            handler=mock_handler,
            plugin_id="plugin-123"
        )
        router.register_endpoint(endpoint)
        
        endpoints = router.get_endpoints_by_plugin("non-existent")
        assert len(endpoints) == 0
