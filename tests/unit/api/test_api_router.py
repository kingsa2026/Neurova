"""
APIRouter 单元测试 - 基于 neurova.core.api_router 当前实现

注意：当前 APIEndpoint 设计为 (path, method 单值, handler, plugin_name)，
端点以 path 为键注册/检索（非 name），插件维度使用 plugin_name（非 plugin_id）。
测试需与 neurova/core/api_router.py 的真实 API 保持一致。
"""

import unittest

try:
    from neurova.core.api_router import APIRouter, APIEndpoint
    HAS_API_ROUTER = True
except ImportError:
    HAS_API_ROUTER = False


@unittest.skipIf(not HAS_API_ROUTER, "APIRouter not available")
class TestAPIRouter(unittest.TestCase):
    """APIRouter 测试类（对齐当前实现 API）"""

    def setUp(self) -> None:
        self.router = APIRouter()

    def _make_handler(self):
        def handler(request=None):
            return {"status": "ok"}
        return handler

    def test_register_endpoint(self) -> None:
        handler = self._make_handler()
        endpoint = APIEndpoint(
            path="/api/test",
            method="GET",
            handler=handler,
            plugin_name="plugin_1",
        )
        self.assertTrue(self.router.register_endpoint(endpoint))

        retrieved = self.router.get_endpoint("/api/test", "GET")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.path, "/api/test")
        self.assertEqual(retrieved.method, "GET")
        self.assertEqual(retrieved.plugin_name, "plugin_1")

    def test_register_duplicate_endpoint(self) -> None:
        handler = self._make_handler()
        endpoint = APIEndpoint(
            path="/api/dup", method="GET", handler=handler, plugin_name="plugin_1"
        )
        self.assertTrue(self.router.register_endpoint(endpoint))
        # 重复注册覆盖，仍返回 True
        self.assertTrue(self.router.register_endpoint(endpoint))

    def test_unregister_endpoint(self) -> None:
        handler = self._make_handler()
        endpoint = APIEndpoint(
            path="/api/remove", method="GET", handler=handler, plugin_name="plugin_1"
        )
        self.router.register_endpoint(endpoint)
        self.assertTrue(self.router.unregister_endpoint("/api/remove", "GET"))
        self.assertIsNone(self.router.get_endpoint("/api/remove", "GET"))

    def test_unregister_nonexistent_endpoint(self) -> None:
        self.assertFalse(self.router.unregister_endpoint("/does_not_exist", "GET"))

    def test_get_endpoints(self) -> None:
        handler = self._make_handler()
        for i in range(3):
            self.router.register_endpoint(APIEndpoint(
                path=f"/api/ep_{i}", method="GET", handler=handler, plugin_name="plugin_1"
            ))
        endpoints = self.router.get_endpoints()
        self.assertEqual(len(endpoints), 3)

    def test_get_endpoints_by_plugin(self) -> None:
        handler = self._make_handler()
        self.router.register_endpoint(APIEndpoint(
            path="/api/p1", method="GET", handler=handler, plugin_name="plugin_1"))
        self.router.register_endpoint(APIEndpoint(
            path="/api/p2", method="GET", handler=handler, plugin_name="plugin_1"))
        self.router.register_endpoint(APIEndpoint(
            path="/api/p3", method="GET", handler=handler, plugin_name="plugin_2"))

        p1_endpoints = self.router.get_endpoints_by_plugin("plugin_1")
        self.assertEqual(len(p1_endpoints), 2)

        p2_endpoints = self.router.get_endpoints_by_plugin("plugin_2")
        self.assertEqual(len(p2_endpoints), 1)

    def test_unregister_plugin_endpoints(self) -> None:
        handler = self._make_handler()
        for i in range(3):
            self.router.register_endpoint(APIEndpoint(
                path=f"/api/plugin/{i}", method="GET", handler=handler, plugin_name="plugin_x"
            ))
        removed = self.router.unregister_plugin_endpoints("plugin_x")
        self.assertEqual(removed, 3)
        self.assertEqual(len(self.router.get_endpoints()), 0)

    def test_get_openapi_spec(self) -> None:
        handler = self._make_handler()
        self.router.register_endpoint(APIEndpoint(
            path="/api/users", method="GET", handler=handler, plugin_name="plugin_1",
            description="List users", tags=["users"],
        ))
        spec = self.router.get_openapi_spec()
        self.assertEqual(spec["openapi"], "3.0.0")
        self.assertIn("/api/users", spec["paths"])
        self.assertIn("get", spec["paths"]["/api/users"])

    def test_get_openapi_spec_empty(self) -> None:
        spec = self.router.get_openapi_spec()
        self.assertEqual(spec["openapi"], "3.0.0")
        self.assertEqual(spec["paths"], {})

    def test_multiple_methods_endpoint(self) -> None:
        handler = self._make_handler()
        # 同一 path 注册多个 method，验证 OpenAPI 规范包含各方法
        self.router.register_endpoint(APIEndpoint(
            path="/api/multi", method="GET", handler=handler, plugin_name="plugin_1"))
        self.router.register_endpoint(APIEndpoint(
            path="/api/multi", method="POST", handler=handler, plugin_name="plugin_1"))
        spec = self.router.get_openapi_spec()
        methods_in_spec = spec["paths"]["/api/multi"]
        self.assertIn("get", methods_in_spec)
        self.assertIn("post", methods_in_spec)


if __name__ == "__main__":
    unittest.main()
