"""MCP 工具闭包绑定回归（晚绑定 → 同 server 多工具全部指向最后一个）

根因：MCPToolClient._sync_tools_to_engine 曾在 `for tool_def in tools:` 循环内
直接定义执行器闭包，并靠循环内重新赋值 `_server_id/_tool_name` 试图"绑定"——
Python 闭包是晚绑定，单元在**调用时**才解析名字，于是所有已注册执行器都解析到
循环结束时的最后一个工具。既有集成测试只注册单工具、或只查注册不执行，故从未暴露。
"""

import asyncio

from neurova.execution_engine.tool_engine import ToolEngine
from neurova.tool_layers.mcp_client import MCPToolClient


def test_each_mcp_tool_executes_its_own_target():
    """同 server 注册多个 MCP 工具时，每个工具必须执行自己的 (server, tool)。"""
    client = MCPToolClient()
    engine = ToolEngine()

    async def fake_execute_tool(server_id, tool_name, params):
        return f"{server_id}/{tool_name}"

    client.execute_tool = fake_execute_tool

    tools = [
        {"name": "web_search", "description": "搜索网页"},
        {"name": "fetch_url", "description": "获取URL内容"},
    ]
    client._sync_tools_to_engine("srv1", tools, engine=engine)

    r1 = asyncio.run(engine.execute("mcp.srv1.web_search", {"query": "a"}))
    r2 = asyncio.run(engine.execute("mcp.srv1.fetch_url", {"query": "b"}))

    assert r1 == "srv1/web_search", f"web_search 被串到别的工具: {r1!r}"
    assert r2 == "srv1/fetch_url", f"fetch_url 被串到别的工具: {r2!r}"


def test_binding_survives_two_servers_synced_into_same_engine():
    """跨 server 顺序同步也不得串：后同步的 server 不得覆盖先注册的工具。"""
    client = MCPToolClient()
    engine = ToolEngine()

    async def fake_execute_tool(server_id, tool_name, params):
        return f"{server_id}/{tool_name}"

    client.execute_tool = fake_execute_tool

    client._sync_tools_to_engine("srvA", [{"name": "alpha", "description": "A"}], engine=engine)
    client._sync_tools_to_engine("srvB", [{"name": "beta", "description": "B"}], engine=engine)

    ra = asyncio.run(engine.execute("mcp.srvA.alpha", {}))
    rb = asyncio.run(engine.execute("mcp.srvB.beta", {}))
    assert ra == "srvA/alpha", ra
    assert rb == "srvB/beta", rb
