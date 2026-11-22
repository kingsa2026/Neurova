"""U7 manifest 运行元数据（D4 升级计划）。

契约：
- _BUILTIN_SCHEMAS 条目可携带 `runtime` 声明位：
  {default_timeout_ms, timeout_ms_clamp:[1000,800000], serializable, ordered_group}
- 首批覆盖 ssh / exec / file 写 / recall 族；
- 执行体（ToolExecutor）执行时读取 runtime 并**单源钳制**——
  schema 声明与执行体不一致时以执行体为准（越界声明被钳进 [1000, 800000]）。
"""

import pytest

from neurova.builtin_tools import (
    clampRuntimeTimeoutMs,
    get_builtin_tool_runtime,
)

#: U7 首批声明 runtime 的工具族（ssh / exec / file 写 / recall）
FIRST_BATCH_TOOLS = [
    "computer_ssh_exec",
    "exec_command",
    "computer_shell",
    "run_code",
    "file_write",
    "file_create",
    "file_edit",
    "file_delete",
    "recall_history",
    "recall_context_span",
    "recall_query",
    "memory_search",
]

CLAMP_LO, CLAMP_HI = 1000, 800000


class TestRuntimeMetadataDeclarations:
    def test_firstBatchToolsDeclareRuntime(self):
        for tool_name in FIRST_BATCH_TOOLS:
            runtime = get_builtin_tool_runtime(tool_name)
            assert isinstance(runtime, dict), f"{tool_name} 缺少 runtime 声明"
            assert runtime.get("timeout_ms_clamp") == [CLAMP_LO, CLAMP_HI], (
                f"{tool_name} 的 clamp 域必须是 [{CLAMP_LO}, {CLAMP_HI}]（单源常量）"
            )
            ms = runtime.get("default_timeout_ms")
            assert isinstance(ms, int) and CLAMP_LO <= ms <= CLAMP_HI, (
                f"{tool_name} 的 default_timeout_ms 越界: {ms}"
            )
            assert isinstance(runtime.get("serializable"), bool), tool_name
            assert isinstance(runtime.get("ordered_group"), bool), tool_name

    def test_runtimeDeclarationDoesNotLeakIntoModelVisibleSchema(self):
        """声明位不进模型可见面（与 capability/sandbox_required 同纪律）：
        to_openai_format 只转发 name/description/parameters。"""
        from neurova.builtin_tools import BuiltinTool, get_builtin_tool_params

        schema = get_builtin_tool_params("file_write")
        assert isinstance(schema.get("runtime"), dict), "runtime 声明挂在 schema 条目上"
        tool = BuiltinTool(
            name="file_write",
            description=schema["description"],
            parameters=schema["parameters"],
        )
        exported = tool.to_openai_format()
        assert "runtime" not in exported["function"], exported


class TestTimeoutClamp:
    def test_clampBelowFloor(self):
        assert clampRuntimeTimeoutMs(5) == CLAMP_LO

    def test_clampAboveCap(self):
        assert clampRuntimeTimeoutMs(999_999_999) == CLAMP_HI

    def test_clampInRangeIsIdentity(self):
        assert clampRuntimeTimeoutMs(45_000) == 45_000

    def test_clampAtBounds(self):
        assert clampRuntimeTimeoutMs(CLAMP_LO) == CLAMP_LO
        assert clampRuntimeTimeoutMs(CLAMP_HI) == CLAMP_HI


class TestExecutorAppliesRuntimeTimeout:
    def _makeExecutor(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        agent = SimpleNamespace(
            config=SimpleNamespace(user_id="u1", agent_id="a1"),
            tool_memory=MagicMock(),
            tool_lifecycle=None,
            _skill_registry=None,
            tool_router=None,
            _current_user_input="x",
            _tool_messages_list=[],
            append_tool_messages=lambda records: None,
        )
        from neurova.tool_executor import ToolExecutor

        return ToolExecutor(agent)

    def test_outOfRangeDeclarationIsClampedByExecutor(self, monkeypatch):
        """红：schema 声明与执行体不一致时以执行体为准——
        声明 10^9 ms（越界）被钳到 800000ms=800s。"""
        executor = self._makeExecutor()
        monkeypatch.setattr(
            "neurova.builtin_tools.get_builtin_tool_runtime",
            lambda name: {"default_timeout_ms": 999_999_999,
                          "timeout_ms_clamp": [CLAMP_LO, CLAMP_HI],
                          "serializable": True, "ordered_group": False},
        )
        assert executor._resolveToolTimeoutSeconds("file_write") == CLAMP_HI / 1000.0

    def test_belowFloorDeclarationIsClampedByExecutor(self, monkeypatch):
        executor = self._makeExecutor()
        monkeypatch.setattr(
            "neurova.builtin_tools.get_builtin_tool_runtime",
            lambda name: {"default_timeout_ms": 5,
                          "timeout_ms_clamp": [CLAMP_LO, CLAMP_HI],
                          "serializable": True, "ordered_group": False},
        )
        assert executor._resolveToolTimeoutSeconds("file_write") == CLAMP_LO / 1000.0

    def test_inRangeDeclarationWinsOverFallbackTable(self, monkeypatch):
        """单源生效：声明在域内 → 执行体按声明值，不落回旧超时表。"""
        executor = self._makeExecutor()
        monkeypatch.setattr(
            "neurova.builtin_tools.get_builtin_tool_runtime",
            lambda name: {"default_timeout_ms": 45_000,
                          "timeout_ms_clamp": [CLAMP_LO, CLAMP_HI],
                          "serializable": True, "ordered_group": False},
        )
        assert executor._resolveToolTimeoutSeconds("file_write") == 45.0

    def test_missingDeclarationFallsBackToTimeoutTable(self, monkeypatch):
        """未声明 runtime → 既有 per-tool 超时表口径不变（零回归）。"""
        executor = self._makeExecutor()
        monkeypatch.setattr("neurova.builtin_tools.get_builtin_tool_runtime", lambda name: None)
        from neurova.agent.tool_coordinator import get_tool_timeout

        assert executor._resolveToolTimeoutSeconds("computer_ssh_exec") == get_tool_timeout(
            "computer_ssh_exec"
        )
