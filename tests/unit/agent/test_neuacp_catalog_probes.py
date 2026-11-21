# -*- coding: utf-8 -*-
"""C1：provider 目录健康探测与握手档案（红→绿，测试先行）。

覆盖 ``neurova/agent/neuacp/catalog.py`` 的 ``probeToolHealth`` /
``presetHandshakeProfiles``：

- which_fn/run_fn 全量注入，**不真实执行子进程**；tmp_path 造假可执行文件
  （Windows .cmd 桩）仅作为 which 命中路径存在。
- 探测无副作用断言：run_fn 只应收到 ``目录 command 首词 + ["--version"]``
  的只读探测命令，绝不携带 ``--acp`` 等会话/登录参数。
"""

import subprocess

import pytest

from neurova.agent.neuacp.catalog import (
    CATALOG,
    PROBE_TIMEOUT_S,
    presetHandshakeProfiles,
    probeToolHealth,
)

_TOOL = "gemini-cli"  # 目录既有 P1 预设，command 首词 "gemini"


def _fakeExe(tmp_path) -> str:
    """Windows .cmd 桩：输出固定 version 文本（测试不真实执行它）。"""
    exe = tmp_path / "fake_stub.cmd"
    exe.write_text("@echo off\r\necho fake-version-1.2.3\r\n", encoding="ascii")
    return str(exe)


def test_unknownToolReportsUnknownToolError():
    result = probeToolHealth("no-such-tool")
    assert result["installed"] is False
    assert result["error"] == "unknown_tool"
    assert result["version"] is None
    assert result["install_hint"] == ""


def test_disabledToolReportsDisabled():
    result = probeToolHealth("trae")
    assert result["installed"] is False
    assert result["error"] == "disabled"
    assert result["install_hint"]  # 目录 hint 保留
    assert result["version"] is None


def test_knownToolNotInstalledNeverRunsVersionProbe():
    seen_cmds = []

    def run_fn(cmd, timeout_s):
        seen_cmds.append(list(cmd))
        return (0, "should-not-run", "")

    result = probeToolHealth(_TOOL, which_fn=lambda name: None, run_fn=run_fn)
    assert result["installed"] is False
    assert result["install_hint"] == CATALOG[_TOOL]["install_hint"]
    assert result["install_hint"]  # hint 非空
    assert result["version"] is None
    assert seen_cmds == []  # 未安装绝不发起 version 子进程


def test_installedVersionParsedAndProbeIsReadOnly(tmp_path):
    exe = _fakeExe(tmp_path)
    seen = {}

    def which_fn(name):
        seen["which"] = name
        return exe

    def run_fn(cmd, timeout_s):
        seen["cmd"] = list(cmd)
        seen["timeout"] = timeout_s
        return (0, "fake-version-1.2.3\nbuild 42\n", "")

    result = probeToolHealth(_TOOL, which_fn=which_fn, run_fn=run_fn)
    assert result["installed"] is True
    assert result["version"] == "fake-version-1.2.3"
    assert result["error"] is None
    # 无副作用断言：探测命令 = 目录 command 首词 + ["--version"]，仅此两项
    head = CATALOG[_TOOL]["command"][0]
    assert seen["which"] == head
    assert seen["cmd"] == [head, "--version"]
    assert "--version" in seen["cmd"]
    assert seen["timeout"] == PROBE_TIMEOUT_S


def test_versionTruncatedTo200Chars(tmp_path):
    exe = _fakeExe(tmp_path)
    long_line = "v" + "9" * 500
    result = probeToolHealth(
        _TOOL,
        which_fn=lambda name: exe,
        run_fn=lambda cmd, t: (0, long_line + "\nsecond\n", ""),
    )
    assert result["installed"] is True
    assert result["version"] == long_line[:200]
    assert len(result["version"]) == 200


def test_runFailureNonZeroKeepsInstalledWithError(tmp_path):
    exe = _fakeExe(tmp_path)
    result = probeToolHealth(
        _TOOL,
        which_fn=lambda name: exe,
        run_fn=lambda cmd, t: (3, "", "boom"),
    )
    # installed 与 version 独立：装了但 version 探测失败仍是 installed=True
    assert result["installed"] is True
    assert result["version"] is None
    assert result["error"]
    assert "boom" in result["error"]


def test_runTimeoutKeepsInstalledWithError(tmp_path):
    exe = _fakeExe(tmp_path)

    def run_fn(cmd, timeout_s):
        raise subprocess.TimeoutExpired(cmd, timeout_s)

    result = probeToolHealth(_TOOL, which_fn=lambda name: exe, run_fn=run_fn)
    assert result["installed"] is True
    assert result["version"] is None
    assert result["error"]


@pytest.mark.parametrize(
    "tool",
    [name for name, entry in CATALOG.items() if not entry.get("disabled")],
)
def test_everyActiveCatalogToolProbesInstalled(tmp_path, tool):
    exe = _fakeExe(tmp_path)
    result = probeToolHealth(
        tool,
        which_fn=lambda name: exe,
        run_fn=lambda cmd, t: (0, "stub-1.0\n", ""),
    )
    assert result["installed"] is True
    assert result["version"] == "stub-1.0"
    assert result["error"] is None


def test_presetHandshakeProfilesContainThreeP1Presets():
    profiles = presetHandshakeProfiles()
    assert set(profiles) == {"gemini", "claude", "codex"}
    for name, profile in profiles.items():
        assert set(profile) == {"initialize", "auth", "session"}, name
        initialize = profile["initialize"]
        assert initialize["protocolVersion"] == "1"
        assert isinstance(initialize["clientCapabilities"], list)
        assert profile["auth"] in {"oauth", "api_key", "subscription"}
        assert profile["session"]["new"] == "session/new"
        assert profile["session"]["prompt"] == "session/prompt"


def test_presetHandshakeProfilesReturnIndependentCopies():
    first = presetHandshakeProfiles()
    first["gemini"]["auth"] = "tampered"
    second = presetHandshakeProfiles()
    assert second["gemini"]["auth"] != "tampered"
