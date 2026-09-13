"""
P0-5 死路与键名 bug 红测（评测 M8/M9）

- M9: mcp_client.list_tools() 写入的键是 server_id（mcp_client.py:279），
  而 neurflow sync_mcp 读 tool.get("server") → 所有 MCP 节点 server 名
  恒为 "default"（mcp:s1:t1 退化成 mcp:default:t1）
- M8: _sync_tools_to_engine(engine=None) 新建 ToolEngine 实例即弃——
  工具注册后被 GC，API GET /tool-layers/tools 永远看不到 MCP 工具
- mcp_client_manager.py 零生产消费方（仅自身测试引用）→ 删除
"""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_REPO = Path(__file__).resolve().parents[3]


# ── 1. M9：sync_mcp 按 server_id 键取服务器名 ────────────────────


class TestSyncMcpServerKey:
    def test_server_id_key_used(self, monkeypatch):
        from neurova.collaboration.neurflow import adapters

        fake_client = SimpleNamespace(
            list_tools=lambda: [
                {"name": "t1", "description": "d", "parameters": [], "server_id": "s1"}
            ]
        )
        monkeypatch.setattr(adapters, "_get_mcp_client", lambda: fake_client)
        registry = MagicMock()

        count = adapters.sync_mcp(registry)

        assert count == 1
        node_def = registry.register.call_args[0][0]
        assert node_def.type == "mcp:s1:t1"
        assert node_def.source_id == "s1:t1"

    def test_legacy_server_key_still_honored(self, monkeypatch):
        """向后兼容：旧式 'server' 键的生产者不被破坏"""
        from neurova.collaboration.neurflow import adapters

        fake_client = SimpleNamespace(
            list_tools=lambda: [
                {"name": "t1", "description": "d", "parameters": [], "server": "legacy"}
            ]
        )
        monkeypatch.setattr(adapters, "_get_mcp_client", lambda: fake_client)
        registry = MagicMock()

        adapters.sync_mcp(registry)

        node_def = registry.register.call_args[0][0]
        assert node_def.type == "mcp:legacy:t1"


# ── 2. M8：engine=None 同步到 API 可见的单例引擎 ─────────────────


class TestSyncToolsEngineTarget:
    def test_sync_without_engine_lands_in_api_singleton(self):
        from neurova.api.endpoints import tool_layers as tl
        from neurova.tool_layers.mcp_client import MCPToolClient

        old = tl._tool_engine
        tl._tool_engine = None
        try:
            client = MCPToolClient(user_id="t")
            client._sync_tools_to_engine(
                "s1", [{"name": "t1", "description": "d", "parameters": {}}]
            )
            engine = tl.get_tool_engine()
            assert engine.get_tool("mcp.s1.t1") is not None
            # 残留处理 2026-09-13：前例向（可能是共享的）单例注册后必须清理，
            # 否则泄漏进 test_explicit_engine_still_respected 的全局无键断言。
            engine.unregister_tool("mcp.s1.t1")
        finally:
            tl._tool_engine = old

    def test_explicit_engine_still_respected(self):
        """集成测试硬约束：显式传 engine 时注册进该实例、不写全局单例。

        残留处理 2026-09-13：原断言依赖"全局干净"，被同目录 MCP 测试在共享
        单例上的注册污染（跨文件状态泄漏）——改为前后像快照对比，契约更严
        （显式注册不得改变全局单例状态）且与既有污染解耦。"""
        from neurova.api.endpoints import tool_layers as tl
        from neurova.execution_engine.tool_engine import ToolEngine
        from neurova.tool_layers.mcp_client import MCPToolClient

        def _in_global():
            eng = tl._tool_engine
            return eng is not None and eng.get_tool("mcp.s1.t1") is not None

        before = _in_global()
        engine = ToolEngine()
        client = MCPToolClient(user_id="t")
        client._sync_tools_to_engine(
            "s1", [{"name": "t1", "description": "d", "parameters": {}}], engine=engine
        )
        assert engine.get_tool("mcp.s1.t1") is not None
        assert _in_global() == before, "显式 engine 注册不得泄漏进全局单例"


# ── 3. 死文件删除 ────────────────────────────────────────────────


class TestDeadFileRemoved:
    def test_mcp_client_manager_deleted(self):
        assert not (_REPO / "neurova" / "execution_engine" / "mcp_client_manager.py").exists()

    def test_mcp_client_manager_not_importable(self):
        import importlib

        try:
            importlib.import_module("neurova.execution_engine.mcp_client_manager")
            raise AssertionError("mcp_client_manager 仍可导入，应已删除")
        except ModuleNotFoundError:
            pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
