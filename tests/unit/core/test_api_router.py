"""
API路由器测试（对齐 neurova/core/api_router.py 真实契约）
端点以 (path, method) 二元组注册，插件端点按 plugin_name 归组。
"""

import pytest
from unittest.mock import MagicMock

from neurova.core.api_router import (
    APIRouter,
    APIEndpoint,
)


def _endpoint(path="/api/test", method="GET", plugin_name="default", **kwargs):
    return APIEndpoint(
        path=path,
        method=method,
        handler=lambda: "OK",
        plugin_name=plugin_name,
        **kwargs,
    )


@pytest.fixture
def router():
    """创建API路由器实例（模块级，供所有测试类使用）"""
    return APIRouter()


class TestAPIEndpoint:
    """测试API端点数据类"""

    def test_create_api_endpoint(self):
        """测试创建API端点（字段面 path/method/handler/plugin_name）"""
        def handler():
            return "OK"

        endpoint = APIEndpoint(
            path="/api/test",
            method="GET",
            handler=handler,
            plugin_name="test_plugin",
            description="测试端点",
            tags=["admin"],
        )

        assert endpoint.path == "/api/test"
        assert endpoint.method == "GET"
        assert endpoint.handler is handler
        assert endpoint.plugin_name == "test_plugin"
        assert endpoint.description == "测试端点"
        assert endpoint.tags == ["admin"]

    def test_api_endpoint_to_dict(self):
        """测试端点字典化"""
        endpoint = _endpoint(description="desc", tags=["t1"])
        data = endpoint.to_dict()

        assert data["path"] == "/api/test"
        assert data["method"] == "GET"
        assert data["plugin_name"] == "default"
        assert data["description"] == "desc"
        assert data["response_model"] is None


class TestAPIRouter:
    """测试API路由器"""

    @pytest.fixture
    def router(self):
        """创建API路由器实例"""
        return APIRouter()

    def test_init(self, router):
        """测试初始化"""
        assert router is not None
        assert router._endpoints == {}

    def test_register_endpoint(self, router):
        """测试注册端点（键为 path → {method: endpoint}）"""
        result = router.register_endpoint(_endpoint())

        assert result is True
        assert router._endpoints["/api/test"]["GET"] is not None

    def test_register_duplicate_endpoint_overwrites(self, router):
        """重复 (path, method) 注册为覆盖语义（warning 后仍成功）"""
        first = _endpoint(description="v1")
        second = _endpoint(description="v2")

        assert router.register_endpoint(first) is True
        assert router.register_endpoint(second) is True

        retrieved = router.get_endpoint("/api/test", "GET")
        assert retrieved.description == "v2"

    def test_register_same_path_different_method(self, router):
        """同路径不同方法可共存"""
        assert router.register_endpoint(_endpoint(method="GET")) is True
        assert router.register_endpoint(_endpoint(method="POST")) is True

        assert len(router.get_endpoints(path="/api/test")) == 2

    def test_unregister_endpoint(self, router):
        """测试注销端点（契约：(path, method) 二元定位）"""
        router.register_endpoint(_endpoint())

        assert router.unregister_endpoint("/api/test", "GET") is True
        assert router._endpoints.get("/api/test") in (None, {})

    def test_unregister_nonexistent_endpoint(self, router):
        """测试注销不存在的端点"""
        assert router.unregister_endpoint("non-existent", "GET") is False

    def test_unregister_plugin_endpoints(self, router):
        """测试注销插件的所有端点"""
        router.register_endpoint(_endpoint(path="/api/plugin1", method="GET", plugin_name="plugin-123"))
        router.register_endpoint(_endpoint(path="/api/plugin2", method="POST", plugin_name="plugin-123"))
        router.register_endpoint(_endpoint(path="/api/other", method="GET", plugin_name="plugin-456"))

        removed = router.unregister_plugin_endpoints("plugin-123")

        assert removed == 2
        assert router.get_endpoint("/api/plugin1", "GET") is None
        assert router.get_endpoint("/api/other", "GET") is not None

    def test_get_endpoint(self, router):
        """测试获取端点（契约：(path, method) 二元查询）"""
        endpoint = _endpoint()
        router.register_endpoint(endpoint)

        retrieved = router.get_endpoint("/api/test", "GET")

        assert retrieved is endpoint

    def test_get_endpoint_method_case_insensitive(self, router):
        """方法名大小写不敏感"""
        router.register_endpoint(_endpoint())

        assert router.get_endpoint("/api/test", "get") is not None

    def test_get_nonexistent_endpoint(self, router):
        """测试获取不存在的端点"""
        assert router.get_endpoint("non-existent", "GET") is None

    def test_get_endpoints_all(self, router):
        """测试获取所有端点"""
        for i in range(3):
            router.register_endpoint(_endpoint(path=f"/api/endpoint{i}"))

        assert len(router.get_endpoints()) == 3

    def test_get_endpoints_filtered(self, router):
        """测试按 path/method 过滤端点"""
        router.register_endpoint(_endpoint(path="/api/a", method="GET"))
        router.register_endpoint(_endpoint(path="/api/a", method="POST"))
        router.register_endpoint(_endpoint(path="/api/b", method="GET"))

        assert len(router.get_endpoints(path="/api/a")) == 2
        assert len(router.get_endpoints(method="GET")) == 2
        assert len(router.get_endpoints(path="/api/a", method="POST")) == 1

    def test_get_endpoints_by_plugin(self, router):
        """测试获取插件的所有端点"""
        router.register_endpoint(_endpoint(path="/api/p0", method="GET", plugin_name="plugin-123"))
        router.register_endpoint(_endpoint(path="/api/p1", method="GET", plugin_name="plugin-123"))
        router.register_endpoint(_endpoint(path="/api/other", method="GET", plugin_name="plugin-456"))

        assert len(router.get_endpoints_by_plugin("plugin-123")) == 2

    def test_get_openapi_spec(self, router):
        """测试生成OpenAPI规范（默认标题 Neurova API）"""
        router.register_endpoint(_endpoint(path="/api/users", method="GET", tags=["users"]))
        router.register_endpoint(_endpoint(path="/api/users", method="POST", tags=["users"]))

        spec = router.get_openapi_spec()

        assert spec["openapi"] == "3.0.0"
        assert "info" in spec
        assert spec["info"]["title"] == "Neurova API"
        assert "/api/users" in spec["paths"]
        assert "get" in spec["paths"]["/api/users"]
        assert "post" in spec["paths"]["/api/users"]
        assert {"name": "users"} in spec["tags"]

    def test_get_status(self, router):
        """测试状态字典键面"""
        router.register_endpoint(_endpoint())

        status = router.get_status()
        assert status["total_endpoints"] == 1
        assert status["total_paths"] == 1
        assert status["plugins"] == {"default": 1}
        assert status["methods"]["GET"] == 1


class TestEdgeCases:
    """测试边界情况"""

    def test_register_endpoint_with_description(self, router):
        """带描述端点注册成功"""
        assert router.register_endpoint(_endpoint(description="描述")) is True

    def test_unregister_plugin_with_no_endpoints(self, router):
        """测试注销无端点的插件"""
        assert router.unregister_plugin_endpoints("non-existent-plugin") == 0

    def test_openapi_spec_empty_router(self, router):
        """测试空路由器的OpenAPI规范"""
        spec = router.get_openapi_spec()
        assert spec["openapi"] == "3.0.0"
        assert spec["paths"] == {}
        assert spec["tags"] == []

    def test_openapi_spec_custom_title(self, router):
        """自定义标题与版本"""
        spec = router.get_openapi_spec(title="Custom API", version="2.0.0")
        assert spec["info"]["title"] == "Custom API"
        assert spec["info"]["version"] == "2.0.0"

    def test_openapi_spec_with_tags(self, router):
        """测试带标签的OpenAPI规范"""
        router.register_endpoint(_endpoint(path="/api/tagged", method="GET", tags=["admin", "users"]))

        spec = router.get_openapi_spec()

        path_spec = spec["paths"]["/api/tagged"]["get"]
        assert path_spec["tags"] == ["admin", "users"]
        tag_names = [t["name"] for t in spec["tags"]]
        assert tag_names == ["admin", "users"]

    def test_get_endpoints_by_nonexistent_plugin(self, router):
        """测试获取不存在的插件端点"""
        router.register_endpoint(_endpoint(plugin_name="plugin-123"))

        assert router.get_endpoints_by_plugin("non-existent") == []
