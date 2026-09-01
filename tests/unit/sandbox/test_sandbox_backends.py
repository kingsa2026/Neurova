"""沙箱执行后端测试（对比文档 P6 修正版）

修正后的现状认知（此前对比报告表述不准确）：
- Neurova 已有 exec_sandbox（bwrap/Seatbelt/AppContainer 占位）且接入治理闭环
- execution_layers 已有 DockerExecutor（但仅 skill_system 显式使用）
- 真实缺口：
  1. Windows AppContainer 是占位（available()=True 但 wrap 无隔离 = 裸跑，本机即 Windows）
  2. 治理 SANDBOX 判定在 Windows 上实际无隔离
  3. computer_use.shell / run_code 硬编码 LocalExecutor，Docker 能力闲置

本套测试锁定 P6 修正实施：治理沙箱路径支持 Docker 后端（跨平台真隔离），
auto 模式按可用性选择，shell 支持 runtime_type 参数。
"""

import platform
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.sandbox import exec_sandbox as exec_sandbox_module
from neurova.sandbox.exec_sandbox import (
    SandboxSeverity,
    AppContainerSandbox,
    execute_in_sandbox,
)


class TestCurrentStateDocumentation:
    def test_appcontainer_is_placeholder_on_windows(self):
        """记录现状：Windows 后端为占位——argv 化后仍无隔离前缀（等同 shell 语义）。

        这是 P6 修正实施的动机：Windows 上治理 SANDBOX 判定此前实际裸跑，
        现已由 execute_in_sandbox_async 的 auto 模式用 Docker 后端补位
        （跨平台真隔离）。
        """
        if platform.system() != "Windows":
            pytest.skip("仅 Windows 环境")
        backend = AppContainerSandbox(SandboxSeverity.NETWORK_OFF)
        # P1-7+P2：占位谎言已清——available 诚实 False；Windows 平台
        # 隔离由 restricted_token（SAFER 特权剥离）承接
        assert backend.available() is False


def _mock_docker_executor(exit_code=0, stdout="ok", stderr=""):
    """构造 mock DockerExecutor（async 接口）"""
    executor = MagicMock()
    executor.start = AsyncMock(return_value=True)
    executor.stop = AsyncMock(return_value=True)
    executor.exec = AsyncMock(
        return_value=SimpleNamespace(exit_code=exit_code, stdout=stdout, stderr=stderr)
    )
    return executor


class TestDockerSandboxBackend:
    @pytest.mark.asyncio
    async def test_docker_backend_executes_in_container(self):
        """backend="docker"：命令经 sh -c 在容器内执行，结果带 backend 标注"""
        mock_executor = _mock_docker_executor(stdout="container-output")
        with (
            patch("neurova.sandbox.exec_sandbox.docker_available", return_value=True),
            patch("neurova.execution_layers.DockerExecutor", return_value=mock_executor),
        ):
            result = await exec_sandbox_module.execute_in_sandbox_async(
                "echo hello", severity=SandboxSeverity.NETWORK_OFF, backend="docker"
            )

        assert result["success"] is True
        assert result["stdout"] == "container-output"
        assert result["backend"] == "docker"
        mock_executor.start.assert_awaited_once()
        # 命令经 sh -c 包装进容器
        call = mock_executor.exec.await_args
        assert call.args[0] == "sh"
        assert call.kwargs.get("args") == ["-c", "echo hello"]
        mock_executor.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_docker_backend_unavailable_returns_error(self):
        """backend="docker" 但 Docker 不可用 → 明确错误而非静默降级"""
        with patch("neurova.sandbox.exec_sandbox.docker_available", return_value=False):
            result = await exec_sandbox_module.execute_in_sandbox_async(
                "echo hi", severity=SandboxSeverity.NETWORK_OFF, backend="docker"
            )

        assert result["success"] is False
        assert "docker" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_auto_prefers_docker_for_isolation_severities(self):
        """backend="auto"：需要隔离（severity != NONE）且 Docker 可用 → 优先容器"""
        mock_executor = _mock_docker_executor()
        with (
            patch("neurova.sandbox.exec_sandbox.docker_available", return_value=True),
            patch("neurova.execution_layers.DockerExecutor", return_value=mock_executor),
        ):
            result = await exec_sandbox_module.execute_in_sandbox_async(
                "echo hi", severity=SandboxSeverity.FULL, backend="auto"
            )

        assert result["backend"] == "docker"

    @pytest.mark.asyncio
    async def test_auto_falls_back_to_platform_sandbox(self):
        """backend="auto"：Docker 不可用 → 回退平台后端（现状行为）"""
        with (
            patch("neurova.sandbox.exec_sandbox.docker_available", return_value=False),
            patch.object(exec_sandbox_module, "get_exec_sandbox") as get_sandbox,
        ):
            fake = MagicMock()
            fake.execute = MagicMock(return_value={"returncode": 0, "stdout": "native", "stderr": ""})
            get_sandbox.return_value = fake

            result = await exec_sandbox_module.execute_in_sandbox_async(
                "echo hi", severity=SandboxSeverity.NETWORK_OFF, backend="auto"
            )

        assert result["stdout"] == "native"
        assert result.get("backend") != "docker"
        fake.execute.assert_called_once()

    def test_sync_entry_unchanged(self):
        """同步便捷入口保持既有签名（治理侧既有调用兼容）"""
        from neurova.sandbox.exec_sandbox import SandboxSeverity as S

        with patch("neurova.sandbox.exec_sandbox.get_exec_sandbox") as get_sandbox:
            fake = MagicMock()
            fake.execute = MagicMock(return_value={"returncode": 0})
            get_sandbox.return_value = fake
            result = execute_in_sandbox("echo hi", severity=S.NONE)
        assert result["returncode"] == 0
        get_sandbox.assert_called_once_with(S.NONE)


class TestShellRuntimeConfigurable:
    @pytest.mark.asyncio
    async def test_shell_defaults_to_local(self):
        from neurova.computer_use import get_computer_use_manager

        mgr = get_computer_use_manager()
        with patch("neurova.execution_layers.LocalExecutor") as local_cls:
            runtime = MagicMock()
            runtime.start = AsyncMock()
            runtime.stop = AsyncMock()
            runtime.exec = AsyncMock(return_value=SimpleNamespace(exit_code=0, stdout="", stderr=""))
            local_cls.return_value = runtime

            await mgr.shell("echo hi")

        local_cls.assert_called_once()

    @pytest.mark.asyncio
    async def test_shell_supports_docker_runtime(self):
        """shell(runtime_type="docker") → 走 RuntimeFactory 创建 Docker 运行时"""
        from neurova.computer_use import get_computer_use_manager

        mgr = get_computer_use_manager()
        with patch("neurova.execution_layers.RuntimeFactory") as factory:
            runtime = MagicMock()
            runtime.start = AsyncMock(return_value=True)
            runtime.stop = AsyncMock(return_value=True)
            runtime.exec = AsyncMock(return_value=SimpleNamespace(exit_code=0, stdout="", stderr=""))
            factory.create.return_value = runtime

            result = await mgr.shell("echo hi", runtime_type="docker")

        assert result["returncode"] == 0
        factory.create.assert_called_once()
