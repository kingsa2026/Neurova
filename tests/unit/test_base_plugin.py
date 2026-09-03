"""
插件基类单元测试

测试 BasePlugin、APIEndpoint 和相关功能。
"""

import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from neurova.plugins.base_plugin import (
    BasePlugin,
    APIEndpoint,
    PluginType,
    PluginPermission,
)
from neurova.plugins.plugin_manifest import PluginManifest, SemVersion


class TestAPIEndpoint:
    """测试 APIEndpoint 类"""

    def test_basic_endpoint(self):
        """测试基本端点"""
        endpoint = APIEndpoint(
            method="POST",
            path="/api/v1/test",
            handler_name="handle_test",
        )
        assert endpoint.method == "POST"
        assert endpoint.path == "/api/v1/test"
        assert endpoint.handler_name == "handle_test"
        assert endpoint.description == ""
        assert endpoint.tags == []

    def test_endpoint_with_description(self):
        """测试带描述的端点"""
        endpoint = APIEndpoint(
            method="GET",
            path="/api/v1/items",
            handler_name="list_items",
            description="获取项目列表",
        )
        assert endpoint.description == "获取项目列表"

    def test_endpoint_with_tags(self):
        """测试带标签的端点"""
        endpoint = APIEndpoint(
            method="POST",
            path="/api/v1/items",
            handler_name="create_item",
            tags=["items", "create"],
        )
        assert endpoint.tags == ["items", "create"]

    def test_endpoint_to_dict(self):
        """测试端点转换为字典"""
        endpoint = APIEndpoint(
            method="POST",
            path="/api/v1/test",
            handler_name="handle_test",
            description="测试端点",
            tags=["test"],
        )
        d = endpoint.to_dict()
        assert d["method"] == "POST"
        assert d["path"] == "/api/v1/test"
        assert d["handler_name"] == "handle_test"
        assert d["description"] == "测试端点"
        assert d["tags"] == ["test"]

    def test_endpoint_from_dict(self):
        """测试从字典创建端点"""
        data = {
            "method": "GET",
            "path": "/api/v1/items",
            "handler_name": "list_items",
            "description": "获取项目列表",
            "tags": ["items"],
        }
        endpoint = APIEndpoint.from_dict(data)
        assert endpoint.method == "GET"
        assert endpoint.path == "/api/v1/items"
        assert endpoint.handler_name == "list_items"


class TestBasePlugin:
    """测试 BasePlugin 基类"""

    def test_abstract_methods(self):
        """测试抽象方法"""
        # BasePlugin 是抽象类，不能直接实例化
        with pytest.raises(TypeError):
            BasePlugin()

    def test_concrete_plugin(self):
        """测试具体插件实现"""

        class TestPlugin(BasePlugin):
            plugin_type = PluginType.SKILL
            api_endpoints = [
                APIEndpoint("GET", "/test", "handle_test"),
            ]
            required_permissions = [PluginPermission.HTTP_REQUEST]

            async def on_initialize(self):
                return None

            async def on_start(self):
                return None

            async def on_stop(self):
                return None

            async def on_destroy(self):
                return None

        # 创建模拟的 manifest
        manifest = PluginManifest(
            plugin_id="test-plugin",
            name="Test Plugin",
            version=SemVersion("1.0.0"),
            plugin_type=PluginType.SKILL,
        )

        plugin = TestPlugin(manifest)
        assert plugin.plugin_id == "test-plugin"
        assert plugin.name == "Test Plugin"
        assert plugin.version == SemVersion("1.0.0")
        assert plugin.plugin_type == PluginType.SKILL
        assert len(plugin.api_endpoints) == 1
        assert plugin.required_permissions == [PluginPermission.HTTP_REQUEST]

    @pytest.mark.asyncio
    async def test_plugin_lifecycle(self):
        """测试插件生命周期"""

        class TestPlugin(BasePlugin):
            plugin_type = PluginType.TOOL

            async def on_initialize(self):
                self.initialized = True

            async def on_start(self):
                self.started = True

            async def on_stop(self):
                self.stopped = True

            async def on_destroy(self):
                self.destroyed = True

        manifest = PluginManifest(
            plugin_id="test-plugin",
            name="Test Plugin",
            version=SemVersion("1.0.0"),
        )

        plugin = TestPlugin(manifest)
        plugin.initialized = False
        plugin.started = False
        plugin.stopped = False
        plugin.destroyed = False

        # 测试生命周期
        await plugin.initialize()
        assert plugin.initialized

        await plugin.start()
        assert plugin.started

        await plugin.stop()
        assert plugin.stopped

        await plugin.destroy()
        assert plugin.destroyed

    @pytest.mark.asyncio
    async def test_plugin_event_subscription(self):
        """测试插件事件订阅"""

        class TestPlugin(BasePlugin):
            plugin_type = PluginType.SKILL

            async def on_initialize(self):
                self.events_received = []

            async def on_start(self):
                pass

            async def on_stop(self):
                pass

            async def on_destroy(self):
                pass

        manifest = PluginManifest(
            plugin_id="test-plugin",
            name="Test Plugin",
            version=SemVersion("1.0.0"),
        )

        plugin = TestPlugin(manifest)
        plugin.events_received = []

        # 模拟事件总线
        mock_event_bus = MagicMock()
        plugin.event_bus = mock_event_bus

        # 测试事件订阅
        def handler(event):
            plugin.events_received.append(event)

        plugin.subscribe("test.event", handler)
        mock_event_bus.subscribe.assert_called_once_with("test.event", handler)

        # 测试事件发布
        plugin.publish_event("test.event", {"data": "test"})
        mock_event_bus.publish.assert_called_once_with("test.event", {"data": "test"})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])