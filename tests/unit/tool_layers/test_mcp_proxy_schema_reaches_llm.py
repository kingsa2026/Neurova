"""
红灯 1（外部手机网关接入批）：MCP 工具的 inputSchema 必须进 agent 决策面。

现状断点：`_discover_mcp_tools` 已把 server 声明的 inputSchema 存进
`_MCPToolProxy.parameters`，但 `orchestrator._build_tools_for_llm` 的对象
转换分支只认 `to_openai_format()`；`_MCPToolProxy` 未实现该方法，落入
builtin 兜底（`get_builtin_tool_params` 对 `mcp.*` 名恒空）→ 模型看到的
parameters 恒为 `{"type":"object","properties":{},"required":[]}`，
调用外部工具只能盲猜参数。
"""
import asyncio
import types

from neurova.tool_layers.tool_router import ToolRouter

FAKE_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "task": {"type": "string", "description": "任务名"},
        "device": {"type": "string", "description": "设备标识"},
    },
    "required": ["task"],
}


class FakeMCPClient:
    """同步 list_tools 的 MCP 客户端桩（与 MCPToolClient.list_tools 同形态）"""

    def list_tools(self):
        return [
            {
                "name": "phone_connect",
                "description": "租约一台手机并返回首屏",
                "parameters": FAKE_INPUT_SCHEMA,
                "server_id": "phonegw",
            }
        ]


def _router_with_mcp() -> ToolRouter:
    router = ToolRouter()
    router.register_mcp_client("phonegw", FakeMCPClient())
    return router


def test_mcp_proxy_exposes_to_openai_format_with_input_schema():
    tools = _router_with_mcp().get_all_tools()
    proxy = tools["mcp.phonegw.phone_connect"]
    assert hasattr(proxy, "to_openai_format"), (
        "_MCPToolProxy 必须暴露 to_openai_format，否则决策面拿不到 inputSchema"
    )
    schema = proxy.to_openai_format()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "mcp.phonegw.phone_connect"
    assert schema["function"]["description"] == "租约一台手机并返回首屏"
    assert schema["function"]["parameters"] == FAKE_INPUT_SCHEMA


def test_build_tools_for_llm_carries_mcp_input_schema():
    from neurova.context.orchestrator import _build_tools_for_llm

    self_stub = types.SimpleNamespace(
        config=types.SimpleNamespace(user_id="u1", agent_id="default"),
        tool_router=_router_with_mcp(),
        skill_registry=None,
    )
    tools = asyncio.run(_build_tools_for_llm(self_stub)) or []
    mcp_tools = [t for t in tools if (t.get("function") or {}).get("name", "").startswith("mcp.")]
    assert mcp_tools, "MCP 工具必须出现在 agent 决策工具面"
    phone = next(t for t in mcp_tools if t["function"]["name"] == "mcp.phonegw.phone_connect")
    assert phone["function"]["parameters"] == FAKE_INPUT_SCHEMA, (
        "模型可见的参数 schema 必须等于 server 声明的 inputSchema，而不是空对象"
    )
