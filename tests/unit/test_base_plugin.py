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
import json
from unittest.mock import AsyncMock, MagicMock

from neurova.plugins import plugin_permissions
from neurova.plugins.base_plugin import (
    BasePlugin,
    APIEndpoint,
    PluginType,
)
from neurova.plugins.plugin_manifest import PluginFrameworkSurface
from neurova.plugins.plugin_manifest import PluginManifest, SemVersion


class _Probe(BasePlugin):
    """最小合法插件（四个抽象钩子齐备），供权限门那一族用例真构造。"""

    async def on_initialize(self):
        pass

    async def on_start(self):
        pass

    async def on_stop(self):
        pass

    async def on_destroy(self):
        pass


def _probePlugin(plugin_id="test-plugin"):
    return _Probe(PluginManifest(plugin_id=plugin_id, name="Probe", version=SemVersion("1.0.0")))


def _grantStore(tmp_path, granted, plugin_id="test-plugin"):
    """预置「已确认」记录：直接铺授权文件，不走 `grant()`——
    走它每铺一次就往真实审计库写一条记录，测试不该有家目录副作用。"""
    from neurova.plugins.plugin_permissions import STORE_VERSION, PluginPermissionStore

    path = tmp_path / "permissions.json"
    path.write_text(
        json.dumps({"version": STORE_VERSION,
                    "grants": {plugin_id: {value: {"granted_by": "qa", "kind": "surface"}
                                            for value in granted}}},
                   ensure_ascii=False),
        encoding="utf-8")
    return PluginPermissionStore(path=str(path), declaredProvider=lambda pid: list(granted))


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
            framework_surfaces = [PluginFrameworkSurface.EMIT_EVENTS]

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
        # §6-159 收口：能力面不在插件类上声明（单点在 skills 的 `permissions`），
        # 插件类只声明框架中介面
        assert plugin.framework_surfaces == [PluginFrameworkSurface.EMIT_EVENTS]

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
    async def test_plugin_event_subscription(self, tmp_path, monkeypatch):
        """测试插件事件订阅（`read:events` / `emit:events` 已逐项确认的那一侧）。"""

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

        monkeypatch.setattr(plugin_permissions, "getPermissionStore",
                            lambda *a, **kw: _grantStore(tmp_path, ["read:events", "emit:events"]))

        # 测试事件订阅
        def handler(event):
            plugin.events_received.append(event)

        plugin.subscribe("test.event", handler)
        mock_event_bus.subscribe.assert_called_once_with("test.event", handler)

        # 测试事件发布
        plugin.publish_event("test.event", {"data": "test"})
        mock_event_bus.publish.assert_called_once_with("test.event", {"data": "test"})

    def test_plugin_event_callsWithoutGrantsAreRefused(self, tmp_path, monkeypatch):
        """P2 改名实（台账 §6-155）：上一档断的是「未经确认也能订阅」，而订阅/发布正是
        事件总线两档框架中介面的强制点（能力面词汇单点在 skills，§6-159）。未授予必须当场拒，
        且**一次都不能落到总线上**——只断「抛了」不够，替身没被碰才算门在门前。
        """
        from neurova.plugins.plugin_errors import PluginError

        monkeypatch.setattr(plugin_permissions, "getPermissionStore",
                            lambda *a, **kw: _grantStore(tmp_path, []))

        plugin = _probePlugin()
        bus = MagicMock()
        plugin.event_bus = bus

        with pytest.raises(PluginError) as caught:
            plugin.subscribe("test.event", lambda e: None)
        assert caught.value.reason == "permission_not_granted"

        with pytest.raises(PluginError) as caught:
            plugin.publish_event("test.event", {"data": 1})
        assert caught.value.reason == "permission_not_granted"

        bus.subscribe.assert_not_called()
        bus.publish.assert_not_called()

    def test_permissionGateIsCheckedBeforeTheBusPresenceCheck(self, tmp_path, monkeypatch):
        """顺序判据：没设总线时也要先过权限门——否则「忘了设 event_bus」会把越权调用
        降成一条 warning，调用方拿到 None 继续跑（§6-126 那一族）。"""
        from neurova.plugins.plugin_errors import PluginError

        monkeypatch.setattr(plugin_permissions, "getPermissionStore",
                            lambda *a, **kw: _grantStore(tmp_path, []))
        plugin = _probePlugin()
        plugin.event_bus = None

        with pytest.raises(PluginError) as caught:
            plugin.subscribe("test.event", lambda e: None)

        assert caught.value.reason == "permission_not_granted"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])