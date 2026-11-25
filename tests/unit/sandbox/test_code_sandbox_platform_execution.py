# -*- coding: utf-8 -*-
"""代码执行沙箱必须把脚本 argv 交给实际隔离后端执行。"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from neurova.sandbox import code_sandbox
from neurova.sandbox.appcontainer import AppContainerSandbox
from neurova.sandbox.exec_sandbox import (
    BubblewrapSandbox,
    SandboxSeverity,
    SeatbeltSandbox,
)
from neurova.sandbox.restricted_token import RestrictedTokenSandbox


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def backend_name(self) -> str:
        return "wrapped-probe"

    def enforced(self) -> bool:
        return True

    def execute_argv(self, argv, timeout=30.0, cwd=None, env=None):
        self.calls.append({"argv": list(argv), "timeout": timeout, "cwd": cwd, "env": env})
        return {
            "sandbox": "wrapped-probe",
            "sandbox_enforced": False,
            "success": True,
            "output": "wrapped-output",
            "error": "",
            "return_code": 0,
        }


def testUnenforcedPlatformBackendIsRejectedBeforeExecution(monkeypatch):
    backend = RecordingBackend()
    backend.enforced = lambda: False
    monkeypatch.setattr(code_sandbox, "docker_available", lambda: False)
    monkeypatch.setattr(code_sandbox, "get_exec_sandbox", lambda severity: backend)
    session = code_sandbox.CodeSandboxSession(backend="auto")
    try:
        with pytest.raises(code_sandbox.SandboxBackendUnavailable, match="无内核隔离"):
            session.execute("print('must-not-run')", "python", 5)
        assert backend.calls == []
    finally:
        session.close()


def testPlatformBackendReceivesScriptArgvInsteadOfRawPopen(monkeypatch):
    backend = RecordingBackend()
    monkeypatch.setattr(code_sandbox, "docker_available", lambda: False)
    monkeypatch.setattr(code_sandbox, "get_exec_sandbox", lambda severity: backend)
    monkeypatch.setattr(code_sandbox, "_resolveExecutable", lambda language: sys.executable)
    monkeypatch.setattr(
        code_sandbox.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("代码执行沙箱绕过了隔离后端，直接启动宿主进程"),
    )
    session = code_sandbox.CodeSandboxSession(backend="auto")
    workspace = session.workspace()
    try:
        result = session.execute("print('wrapped-output')", "python", 7.5)
        assert len(backend.calls) == 1
        call = backend.calls[0]
        assert call["argv"][0] == sys.executable
        assert call["timeout"] == 7.5
        assert call["cwd"] == str(workspace)
        source = Path(call["argv"][-1])
        assert source.is_file()
        assert source.read_text(encoding="utf-8") == "print('wrapped-output')"
        assert call["env"]["PYTHONIOENCODING"] == "utf-8"
    finally:
        session.close()

    assert result["backend"] == "wrapped-probe"
    assert result["enforced"] is False
    assert result["stdout"] == "wrapped-output"
    assert result["exit_code"] == 0


@pytest.mark.parametrize("backendType", [AppContainerSandbox, RestrictedTokenSandbox])
def testWindowsBackendArgvStartsInterpreterDirectly(monkeypatch, backendType):
    backend = backendType(SandboxSeverity.NETWORK_OFF)
    captured = {}

    def recordExecute(command, timeout=30.0, cwd=None, env=None, _direct_app=None):
        captured.update(command=command, timeout=timeout, cwd=cwd, env=env, direct=_direct_app)
        return {"return_code": 0}

    monkeypatch.setattr(backend, "execute", recordExecute)
    executable = r"C:\Program Files\Python\python.exe"
    script = r"C:\work dir\snippet.py"
    backend.execute_argv([executable, script], timeout=4.0, cwd=r"C:\work dir", env={"X": "1"})

    assert captured["direct"] == executable
    assert script in captured["command"]
    assert captured["timeout"] == 4.0
    assert captured["cwd"] == r"C:\work dir"
    assert captured["env"] == {"X": "1"}


def testBubblewrapBindsSandboxWorkspaceAfterTmpfs():
    wrapped = BubblewrapSandbox(SandboxSeverity.NETWORK_OFF).wrap_argv(
        "python /tmp/work/snippet.py", cwd="/tmp/work"
    )
    assert wrapped.index("--tmpfs") < wrapped.index("--bind")
    bindIndex = wrapped.index("--bind")
    assert wrapped[bindIndex:bindIndex + 3] == ["--bind", "/tmp/work", "/tmp/work"]
    assert wrapped.index("--bind") < wrapped.index("--")


@pytest.mark.parametrize(
    ("backendType", "executableName"),
    [(BubblewrapSandbox, "bwrap"), (SeatbeltSandbox, "sandbox-exec")],
)
def testIsolatingBackendAlsoWrapsRawProcessArgv(backendType, executableName):
    backend = backendType(SandboxSeverity.NETWORK_OFF)
    argv = ["python", "-c", "print('hello world')"]

    wrapped = backend.wrap_process_argv(argv, cwd="/tmp/work")

    assert wrapped != argv
    assert wrapped[0] == executableName
    assert wrapped[-3:] == ["sh", "-c", "python -c 'print('\"'\"'hello world'\"'\"')'"]


@pytest.mark.skipif(os.name != "nt", reason="Windows 环境块语义")
@pytest.mark.parametrize("backendType", [AppContainerSandbox, RestrictedTokenSandbox])
def testWindowsBackendPassesEnvironmentToDirectChild(backendType, tmp_path):
    backend = backendType(SandboxSeverity.NETWORK_OFF)
    if not backend.available():
        pytest.skip(f"{backend.backend_name()} 不可用")
    env = dict(os.environ)
    env["NEUROVA_SANDBOX_ENV_PROBE"] = "environment-block-ok"
    node = shutil.which("node")
    assert node is not None

    result = backend.execute_argv(
        [node, "-e", "process.stdout.write(process.env.NEUROVA_SANDBOX_ENV_PROBE || 'missing')"],
        timeout=30,
        cwd=str(tmp_path),
        env=env,
    )

    assert result["success"] is True, result
    assert result["output"] == "environment-block-ok"
