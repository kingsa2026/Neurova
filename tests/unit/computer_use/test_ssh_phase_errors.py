"""SSH 失败相位追踪（U3）

验收：
- 连接失败/认证失败/超时且零输出 → RemoteNotExecutedError（executed=False,
  retryable=True, phase=connect|auth|timeout）
- 已获部分输出后中断 → executed="unknown"、retryable=False（不可盲目重试）
- tool_executor ssh 分支把 RemoteNotExecutedError 映射为结构化错误载荷
  {error_code:"REMOTE_NOT_EXECUTED", phase, retryable, executed}；其余工具行为不变
"""

import socket

import pytest

paramiko = pytest.importorskip("paramiko")

from neurova.computer_use.ssh_runner import (
    RemoteNotExecutedError,
    run_ssh_command,
)


def _freeClosedPort() -> int:
    """取一个当前无人监听的本地端口（真实 socket 拒连，不依赖桩）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class FakeChannel:
    def __init__(self, status=0):
        self._status = status

    def recv_exit_status(self):
        return self._status


class FakeStd:
    """可编排的 stdout/stderr 替身：read 行为按脚本走。"""

    def __init__(self, data=b"", exc=None, status=0):
        self._data = data
        self._exc = exc
        self.channel = FakeChannel(status)

    def read(self):
        if self._exc is not None:
            raise self._exc
        return self._data


class TestPhaseClassification:
    def test_connect_refused_real_socket(self):
        """真实 socket 拒连 → phase=connect，判定未执行、可重试。"""
        with pytest.raises(RemoteNotExecutedError) as ei:
            run_ssh_command("127.0.0.1", "ls", port=_freeClosedPort(),
                            user="u", password="p", timeout=5.0)
        assert ei.value.phase == "connect"
        assert ei.value.executed is False
        assert ei.value.retryable is True

    def test_auth_failure_classified(self):
        class AuthBoom:
            def set_missing_host_key_policy(self, p):
                pass

            def connect(self, **kw):
                raise paramiko.AuthenticationException("bad password")

            def close(self):
                pass

        with pytest.raises(RemoteNotExecutedError) as ei:
            run_ssh_command("h", "ls", user="u", password="pw",
                            client_factory=lambda: AuthBoom())
        assert ei.value.phase == "auth"
        assert ei.value.executed is False
        assert ei.value.retryable is True

    def test_timeout_with_zero_output_is_retryable(self):
        class TimeoutClient:
            def set_missing_host_key_policy(self, p):
                pass

            def connect(self, **kw):
                pass

            def exec_command(self, cmd, timeout=None):
                return (None, FakeStd(exc=socket.timeout("timed out")), FakeStd())

            def close(self):
                pass

        with pytest.raises(RemoteNotExecutedError) as ei:
            run_ssh_command("h", "longjob", client_factory=lambda: TimeoutClient())
        assert ei.value.phase == "timeout"
        assert ei.value.executed is False
        assert ei.value.retryable is True

    def test_partial_output_interrupt_is_not_blindly_retryable(self):
        class HalfDoneClient:
            def set_missing_host_key_policy(self, p):
                pass

            def connect(self, **kw):
                pass

            def exec_command(self, cmd, timeout=None):
                # stdout 已读到部分输出，stderr 读取时连接中断
                return (None, FakeStd(data=b"partial-out"),
                        FakeStd(exc=socket.timeout("connection reset")))

            def close(self):
                pass

        with pytest.raises(RemoteNotExecutedError) as ei:
            run_ssh_command("h", "longjob", client_factory=lambda: HalfDoneClient())
        assert ei.value.executed == "unknown"
        assert ei.value.retryable is False

    def test_success_path_unchanged(self):
        class OkClient:
            def set_missing_host_key_policy(self, p):
                pass

            def connect(self, **kw):
                pass

            def exec_command(self, cmd, timeout=None):
                return (None, FakeStd(data=b"out"), FakeStd(data=b"err", status=0))

            def close(self):
                pass

        out = run_ssh_command("h", "ls", client_factory=lambda: OkClient())
        assert out == {"returncode": 0, "stdout": "out", "stderr": "err"}


class TestToolExecutorMapping:
    @pytest.mark.asyncio
    async def test_remote_not_executed_maps_to_structured_payload(self, monkeypatch):
        from neurova.tool_executor import ToolExecutor

        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": None, "_current_user_id": "u1"})()

        def boom(*a, **k):
            raise RemoteNotExecutedError("SSH 认证失败（u@h1）: bad password", phase="auth")

        monkeypatch.setattr(
            "neurova.computer_use.ssh_runner.resolve_ssh_credentials",
            lambda u, h: {"user": "root", "port": 22},
        )
        monkeypatch.setattr("neurova.computer_use.ssh_runner.run_ssh_command", boom)

        async def fake_emit(self, *a, **k):
            return None

        monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
        out = await inst._execute_computer_ssh_exec({"host": "h1", "command": "ls"})
        assert out["success"] is False
        assert out["error_code"] == "REMOTE_NOT_EXECUTED"
        assert out["phase"] == "auth"
        assert out["retryable"] is True
        assert out["executed"] is False
        assert out["host"] == "h1" and out["command"] == "ls"

    @pytest.mark.asyncio
    async def test_unknown_retryability_maps_through(self, monkeypatch):
        """部分输出后中断（executed=unknown、retryable=False）原样进载荷，绝不谎报可重试。"""
        from neurova.tool_executor import ToolExecutor

        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": None, "_current_user_id": "u1"})()

        def boom(*a, **k):
            raise RemoteNotExecutedError("SSH 命令执行中断", phase="exec",
                                         retryable=False, executed="unknown")

        monkeypatch.setattr(
            "neurova.computer_use.ssh_runner.resolve_ssh_credentials",
            lambda u, h: {"user": "root", "port": 22},
        )
        monkeypatch.setattr("neurova.computer_use.ssh_runner.run_ssh_command", boom)

        async def fake_emit(self, *a, **k):
            return None

        monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
        out = await inst._execute_computer_ssh_exec({"host": "h1", "command": "reboot"})
        assert out["error_code"] == "REMOTE_NOT_EXECUTED"
        assert out["executed"] == "unknown"
        assert out["retryable"] is False
