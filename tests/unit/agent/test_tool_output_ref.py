"""工具大输出 OutputRef 落盘引用测试

ToolResult{Success, Output, OutputRef, Data, Error}——大输出
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
        assert maybe_output_ref("t", result, workspace, success=True) is result

    def test_small_result_unchanged(self, workspace):
        from neurova.agent import tool_output_ref
        from neurova.agent.tool_output_ref import maybe_output_ref

        tool_output_ref.install_tool_output_ref(max_chars=1000)
        result = {"success": True, "result": "x" * 100}
        assert maybe_output_ref("t", result, workspace, success=True) is result

    def test_big_result_replaced_by_ref(self, workspace):
        from neurova.agent import tool_output_ref
        from neurova.agent.tool_output_ref import maybe_output_ref

        tool_output_ref.install_tool_output_ref(max_chars=1000)
        result = {"success": True, "result": "x" * 5000}
        ref = maybe_output_ref("big_tool", result, workspace, success=True)

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

    def test_failureResult_isNeverFoldedIntoARef(self, workspace):
        """失败结果不得被折叠成无诊断信息的引用（CI 实测根因）。

        失败正文就是诊断载体（`error` / `stderr` / `exit_code`），引用结构里
        只有 `{path, size_bytes, truncated, preview}` —— 在咽喉处先折叠，等于
        把 T-01 修好的"诊断蒸发"原样放回来。体量折叠的**单源**是回环处的
        `apply_offload_policy`（head+tail 预览 + 可回读指针），它保留诊断；
        本层只该管成功结果。夹具按生产判据显式传入 `success`。
        """
        from neurova.agent import tool_output_ref
        from neurova.agent.tool_output_ref import maybe_output_ref

        tool_output_ref.install_tool_output_ref(max_chars=100)
        result = {"success": False, "error": "boom", "stderr": "x" * 5000, "exit_code": 3}
        assert maybe_output_ref("t", result, workspace, success=False) is result

    def test_successResult_stillFolds(self, workspace):
        """反例对照：成功结果照旧折叠（负例不是探针断了才看起来像拦住了）。"""
        from neurova.agent import tool_output_ref
        from neurova.agent.tool_output_ref import maybe_output_ref

        tool_output_ref.install_tool_output_ref(max_chars=100)
        result = {"success": True, "result": "x" * 5000}
        assert maybe_output_ref("t", result, workspace, success=True) is not result

    def test_no_workspace_skips(self, workspace):
        """无工作区（None）时不落盘，原样返回（诚实降级优于丢输出）。"""
        from neurova.agent import tool_output_ref
        from neurova.agent.tool_output_ref import maybe_output_ref

        tool_output_ref.install_tool_output_ref(max_chars=100)
        result = {"success": True, "result": "x" * 500}
        assert maybe_output_ref("t", result, None, success=True) is result

    def test_non_dict_result_untouched(self, workspace):
        from neurova.agent import tool_output_ref
        from neurova.agent.tool_output_ref import maybe_output_ref

        tool_output_ref.install_tool_output_ref(max_chars=10)
        assert maybe_output_ref("t", "small", workspace, success=True) == "small"

    def test_install_idempotent(self):
        from neurova.agent import tool_output_ref

        h1 = tool_output_ref.install_tool_output_ref()
        h2 = tool_output_ref.install_tool_output_ref()
        assert h1 is h2
