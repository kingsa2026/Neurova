"""
MCP 工具发现 dict 形态修复（2026-09-09，kai 3.5万 token prompt 排查副产物）

根因：ToolRouter._discover_mcp_tools 对 MCPToolClient.list_tools() 返回的
**dict** 用 getattr(t, "name", None) or str(t) 取名——dict 恒无 name 属性，
整个 dict 的 repr 变成工具名（1.1 万字符 blob），且按「命名空间名+裸名」
双形态注册后同一 blob 进 schema 两份；description/parameters 同路径取空。
后果：模型收到超长非法工具名（>64 字符，OpenAI 契约上限）且无法调用。
"""
import pytest

from neurova.tool_layers.tool_router import ToolRouter


def _fs_server_client(tools: list) -> object:
    """模拟 MCPToolClient.list_tools() 的真实返回形态：List[dict]。"""

    class _Client:
        def list_tools(self):
            return tools

    return _Client()


FS_TOOLS = [
    {
        "name": "read_text_file",
        "description": "Read the complete contents of a file as text.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
    },
    {
        "name": "write_file",
        "description": "Create a new file or completely overwrite an existing file.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
    },
]


class TestMCPDictShapeDiscovery:
    """list_tools() 返回 dict 列表时的发现契约。"""

    def setup_method(self):
        self.router = ToolRouter()
        self.router._mcp_clients = {"filesystem": _fs_server_client(FS_TOOLS)}

    def test_names_are_real_names_not_dict_repr(self):
        """工具名必须是真实 name，不允许出现 dict repr blob。"""
        tools = self.router._discover_mcp_tools()
        assert tools, "应发现 MCP 工具"
        for name in tools:
            assert "{" not in name and "}" not in name, f"工具名仍是 dict blob: {name!r}"

    def test_namespace_and_bare_names(self):
        """命名空间名 + 裸名双注册，且都用真实名字。"""
        tools = self.router._discover_mcp_tools()
        assert "mcp.filesystem.read_text_file" in tools
        assert "read_text_file" in tools
        assert tools["mcp.filesystem.read_text_file"].server_id == "filesystem"

    def test_description_and_parameters_extracted(self):
        """description/parameters 从 dict 提取，而非恒空默认。"""
        tools = self.router._discover_mcp_tools()
        proxy = tools["mcp.filesystem.read_text_file"]
        assert "Read the complete contents" in proxy.description
        assert proxy.parameters.get("properties", {}).get("path") is not None

    def test_dict_blob_name_would_be_absent(self):
        """防回归：旧实现 str(dict) 生成的 blob 名不得存在。"""
        tools = self.router._discover_mcp_tools()
        blob = str(FS_TOOLS[0])
        assert blob not in tools
        assert f"mcp.filesystem.{blob}" not in tools

    def test_entry_without_name_skipped(self):
        """无 name 的条目跳过（不产出 str(dict) 垃圾名）。"""
        self.router._mcp_clients = {
            "bad": _fs_server_client([{"description": "no name here"}])
        }
        tools = self.router._discover_mcp_tools()
        assert tools == {}

    def test_object_shape_still_supported(self):
        """对象形态（有 .name 属性）向后兼容。"""
        class _ObjTool:
            name = "obj_tool"
            description = "object shaped"
            parameters = {"type": "object", "properties": {}}

        self.router._mcp_clients = {"srv": _fs_server_client([_ObjTool()])}
        tools = self.router._discover_mcp_tools()
        assert "mcp.srv.obj_tool" in tools
        assert tools["mcp.srv.obj_tool"].description == "object shaped"

    def test_get_all_tools_end_to_end(self):
        """端到端：get_all_tools 聚合后 MCP 工具名合法（orchestrator 消费面）。"""
        all_tools = self.router.get_all_tools()
        mcp_names = [n for n in all_tools if n.startswith("mcp.")]
        assert len(mcp_names) == 2
        for n in mcp_names:
            assert len(n) <= 64, f"工具名超 OpenAI 64 字符上限: {n!r}"
