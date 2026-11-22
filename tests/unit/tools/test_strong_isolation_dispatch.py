# -*- coding: utf-8 -*-
"""U5 分派接线：run_code/exec_command 的 isolation="strong" 走容器档（红→绿）。

契约（实施计划 U5 + 拍板 D-T1=Docker 容器档）：
- run_code / exec_command 增加 ``isolation`` 参数（"default" | "strong"，缺省 default）；
- strong → ``sandbox/container_sandbox.ContainerSandbox.run_code``（真容器档）；
- docker 不可用 → 结构化 ``TOOL_UNSUPPORTED`` 拒绝，**不回退明文执行**（fail-closed）；
- default → 原路径不变（既有行为零变化）。

红（现网行为）：isolation 参数被忽略，strong 按旧档（本机明文）执行。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from neurova.tool_executor import TOOL_UNSUPPORTED_CODE, ToolExecutor  # noqa: E402


def _makeExecutor() -> ToolExecutor:
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
    return ToolExecutor(agent)


class _StubSandbox:
    """容器档替身：记录调用并返回**真实** SandboxResult（测分派，不测容器本身）。

    断言目标是"strong 是否被分派到容器档"，不是容器执行语义——后者由
    container_sandbox 自己的测试与 live-verify 承担。替身返回真 dataclass，
    不用 MagicMock 冒充业务对象。
    """

    lastCode: str | None = None
    lastKwargs: dict | None = None
    availabilityValue = True

    def __init__(self, *args, **kwargs):
        pass

    def availability(self) -> bool:
        return _StubSandbox.availabilityValue

    def run_code(self, code, *, language="python", timeout_s=60.0, workdir_files=None):
        # 语言先验与真实 ContainerSandbox 同契约（_requirePython 先于可用性判定）
        from neurova.sandbox.container_sandbox import (
            SandboxLanguageUnsupported,
            SandboxResult,
        )

        if (language or "").strip().lower() != "python":
            raise SandboxLanguageUnsupported(
                f"语言 '{language}' 不受容器档支持：本期仅 python")
        _StubSandbox.lastCode = code
        _StubSandbox.lastKwargs = {
            "language": language, "timeout_s": timeout_s, "workdir_files": workdir_files,
        }
        return SandboxResult(
            stdout="container-ok\n", stderr="", exit_code=0,
            enforced=True, duration_ms=1.0, backend="docker",
            timed_out=False, detail="",
        )


@pytest.fixture
def stubSandbox(monkeypatch):
    import neurova.sandbox.container_sandbox as cs

    _StubSandbox.lastCode = None
    _StubSandbox.lastKwargs = None
    _StubSandbox.availabilityValue = True
    monkeypatch.setattr(cs, "ContainerSandbox", _StubSandbox)
    return _StubSandbox


class TestRunCodeStrongIsolation:
    @pytest.mark.asyncio
    async def test_strongDispatchesToContainerSandbox(self, stubSandbox):
        """绿判据：strong 真走容器档（docker 桩可用时）。"""
        executor = _makeExecutor()
        result = await executor._execute_run_code({
            "code": "print(6*7)", "language": "python", "isolation": "strong",
        })
        assert result.get("isolation") == "strong", f"应标记 strong 档: {result}"
        assert result.get("enforced") is True, f"应如实标记已强制隔离: {result}"
        assert "container-ok" in str(result.get("stdout")), f"应是容器档产物: {result}"
        assert stubSandbox.lastCode == "print(6*7)", "容器档应收到原代码"

    @pytest.mark.asyncio
    async def test_strongWithDockerUnavailableFailsClosed(self, stubSandbox):
        """绿判据：docker 不可用 → 结构化 TOOL_UNSUPPORTED，不回退明文执行。"""
        stubSandbox.availabilityValue = False
        executor = _makeExecutor()
        result = await executor._execute_run_code({
            "code": "print(1)", "language": "python", "isolation": "strong",
        })
        assert result.get("error_code") == TOOL_UNSUPPORTED_CODE, (
            f"docker 不可用必须结构化拒绝: {result}")
        assert result.get("success") is False

    @pytest.mark.asyncio
    async def test_strongUnsupportedLanguageFailsClosed(self, stubSandbox):
        """容器档仅 python：语言不支持 → 结构化拒绝（不悄悄换语义）。"""
        executor = _makeExecutor()
        result = await executor._execute_run_code({
            "code": "echo hi", "language": "shell", "isolation": "strong",
        })
        assert result.get("error_code") == TOOL_UNSUPPORTED_CODE, (
            f"容器档不支持的语言应结构化拒绝: {result}")

    @pytest.mark.asyncio
    async def test_strongIgnoredIsRedBehavior(self):
        """红判据：现网 isolation=strong 被忽略，按本机旧档执行（未走容器档）。"""
        executor = _makeExecutor()
        result = await executor._execute_run_code({
            "code": "print('red-probe')", "language": "python", "isolation": "strong",
        })
        # 红灯形态：本机执行成功，且既无 isolation 标记也无 enforced 标记
        assert result.get("isolation") != "strong" and result.get("enforced") is not True, (
            f"若已接线则本断言转绿: {result}")

    @pytest.mark.asyncio
    async def test_defaultKeepsLegacyPath(self, stubSandbox):
        """default（缺省）走原路径：不进容器档。"""
        executor = _makeExecutor()
        result = await executor._execute_run_code({
            "code": "print('legacy')", "language": "python",
        })
        assert stubSandbox.lastCode is None, "default 档不得进容器档"
        assert result.get("isolation") in (None, "default"), f"缺省档位: {result}"

    def test_containerSandboxLanguageGateIsReal(self):
        """真实容器档的语言先验：非 python 在执行前即结构化拒绝（无需 docker）。"""
        from neurova.sandbox.container_sandbox import (
            ContainerSandbox,
            SandboxLanguageUnsupported,
        )

        with pytest.raises(SandboxLanguageUnsupported):
            ContainerSandbox().run_code("print(1)", language="shell")

    @pytest.mark.asyncio
    async def test_invalidIsolationValueRejected(self):
        executor = _makeExecutor()
        result = await executor._execute_run_code({
            "code": "print(1)", "isolation": "windmill",
        })
        assert result.get("error_code") == TOOL_UNSUPPORTED_CODE, (
            f"未知档位应结构化拒绝: {result}")


class TestExecCommandStrongIsolation:
    @pytest.mark.asyncio
    async def test_strongDispatchesToContainerSandbox(self, stubSandbox):
        """绿判据：exec_command strong → 命令在容器档内执行。"""
        executor = _makeExecutor()
        result = await executor._execute_exec_command({
            "command": "echo hello-strong", "isolation": "strong",
        })
        assert result.get("isolation") == "strong", f"应标记 strong 档: {result}"
        assert result.get("enforced") is True, f"应如实标记已强制隔离: {result}"
        assert stubSandbox.lastCode and "echo hello-strong" in stubSandbox.lastCode, (
            "shell 命令应被送进容器档执行")

    @pytest.mark.asyncio
    async def test_strongWithDockerUnavailableFailsClosed(self, stubSandbox):
        """绿判据：docker 不可用 → 结构化 TOOL_UNSUPPORTED，不回退明文执行。"""
        stubSandbox.availabilityValue = False
        executor = _makeExecutor()
        result = await executor._execute_exec_command({
            "command": "echo hi", "isolation": "strong",
        })
        assert result.get("error_code") == TOOL_UNSUPPORTED_CODE, (
            f"docker 不可用必须结构化拒绝: {result}")
        assert result.get("success") is False

    @pytest.mark.asyncio
    async def test_strongIgnoredIsRedBehavior(self):
        """红判据：现网 exec_command 的 isolation=strong 被忽略（按本机会话档执行）。"""
        from neurova.execution_engine import shell_sessions

        executor = _makeExecutor()
        try:
            result = await executor._execute_exec_command({
                "command": "echo red-probe", "isolation": "strong",
            })
            assert result.get("isolation") != "strong" and result.get("enforced") is not True, (
                f"若已接线则本断言转绿: {result}")
        finally:
            await shell_sessions.get_shell_session_manager().kill_all()
            shell_sessions.reset_shell_session_manager()
