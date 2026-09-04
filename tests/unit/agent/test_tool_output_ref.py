"""工具大输出 OutputRef 落盘引用测试（OpenOcta 启发 P1-6）

OpenOcta：ToolResult{Success, Output, OutputRef, Data, Error}——大输出
落盘为文件，上下文只放 {Path, SizeBytes, Truncated} 引用，模型可用 read
工具按需取。Neurova 的 file_read 接收绝对路径，落盘引用天然可回读。

装配语义对齐 tool_circuit_breaker / tool_param_guard：**默认不安装**
（install_tool_output_ref 显式装配，幂等），未安装时恒为透传。
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture(autouse=True)
def _clean_install():
    from neurova.agent import tool_output_ref

    tool_output_ref.uninstall_tool_output_ref(force=True)
    yield
    tool_output_ref.uninstall_tool_output_ref(force=True)


class TestOutputRef:
    def test_passthrough_when_not_installed(self, workspace):
        from neurova.agent.tool_output_ref import maybe_output_ref

        result = {"success": True, "result": "x" * 100}
        assert maybe_output_ref("t", result, workspace) is result

    def test_small_result_unchanged(self, workspace):
        from neurova.agent import tool_output_ref
        from neurova.agent.tool_output_ref import maybe_output_ref

        tool_output_ref.install_tool_output_ref(max_chars=1000)
        result = {"success": True, "result": "x" * 100}
        assert maybe_output_ref("t", result, workspace) is result

    def test_big_result_replaced_by_ref(self, workspace):
        from neurova.agent import tool_output_ref
        from neurova.agent.tool_output_ref import maybe_output_ref

        tool_output_ref.install_tool_output_ref(max_chars=1000)
        result = {"success": True, "result": "x" * 5000}
        ref = maybe_output_ref("big_tool", result, workspace)

        assert ref is not result
        assert ref["success"] is True
        ore = ref["output_ref"]
        assert ore["truncated"] is True
        # size_bytes = 落盘 JSON 全文字节数（载荷 5000 + 结构开销）
        assert ore["size_bytes"] > 5000
        # preview 是序列化 JSON 前缀（载荷在 "result": " 之后出现）
        assert "x" in ore["preview"]
        # 落盘文件真实存在且可回读（file_read 契约：绝对路径）
        path = ore["path"]
        assert path.endswith(".json")
        with open(path, "r", encoding="utf-8") as f:
            stored = json.load(f)
        assert stored["result"] == "x" * 5000

    def test_error_result_preserves_success_false(self, workspace):
        from neurova.agent import tool_output_ref
        from neurova.agent.tool_output_ref import maybe_output_ref

        tool_output_ref.install_tool_output_ref(max_chars=100)
        result = {"error": "boom " + "x" * 500}
        ref = maybe_output_ref("t", result, workspace)
        assert ref["success"] is False
        assert ref["output_ref"]["truncated"] is True

    def test_no_workspace_skips(self, workspace):
        """无工作区（None）时不落盘，原样返回（诚实降级优于丢输出）。"""
        from neurova.agent import tool_output_ref
        from neurova.agent.tool_output_ref import maybe_output_ref

        tool_output_ref.install_tool_output_ref(max_chars=100)
        result = {"success": True, "result": "x" * 500}
        assert maybe_output_ref("t", result, None) is result

    def test_non_dict_result_untouched(self, workspace):
        from neurova.agent import tool_output_ref
        from neurova.agent.tool_output_ref import maybe_output_ref

        tool_output_ref.install_tool_output_ref(max_chars=10)
        assert maybe_output_ref("t", "small", workspace) == "small"

    def test_install_idempotent(self):
        from neurova.agent import tool_output_ref

        h1 = tool_output_ref.install_tool_output_ref()
        h2 = tool_output_ref.install_tool_output_ref()
        assert h1 is h2
