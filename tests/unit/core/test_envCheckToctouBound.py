# -*- coding: utf-8 -*-
"""CORE-10：环境检查的下载与提权执行不得共享固定 TEMP 路径，执行前必须绑定内容。

根因：安装包固定落在 `%TEMP%/neurova_envcheck/vc_redist.x64.exe`，下载、验签、
提权执行之间没有锁也没有内容固定；PowerShell 命令用单引号直插路径。本地并发
或路径植入可在验签后替换待执行文件（TOCTOU）。

判据：
- 每次运行使用独立私有临时目录，结束后目录被清理（不共享固定路径）；
- 提权命令在 Start-Process 之前用 Get-FileHash 复核「验签时算出的 SHA-256」，
  内容被替换即退出 86；路径按 PowerShell 单引号规则转义（`'` → `''`）。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from neurova.core import env_check


def _wire_success(monkeypatch, calls: list, run_install=None):
    monkeypatch.setattr(env_check, "_IS_WINDOWS", True)
    monkeypatch.setattr(env_check, "is_vc_redist_installed", lambda: False)

    def fake_download(url, dest: Path) -> None:
        calls.append(("download", Path(dest)))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"MZ-fake-installer")

    monkeypatch.setattr(env_check, "_download_file", fake_download)
    monkeypatch.setattr(env_check, "_verify_authenticode", lambda exe: True)
    monkeypatch.setattr(env_check, "_run_elevated_installer", run_install or (lambda exe, digest: 0))


def testEachRunUsesPrivateTempDirAndCleansIt(monkeypatch):
    """两次运行不得复用同一固定 TEMP 路径；运行后私有目录被清理。"""
    calls: list = []
    _wire_success(monkeypatch, calls)

    r1 = env_check.ensure_vc_redist()
    r2 = env_check.ensure_vc_redist()

    assert r1.reason == "ok" and r2.reason == "ok"
    dests = [d for kind, d in calls if kind == "download"]
    assert len(dests) == 2
    assert dests[0].parent != dests[1].parent, "两次运行共用同一下载路径（固定 TEMP）"
    fixed = Path(tempfile.gettempdir()) / "neurova_envcheck"
    assert dests[0].parent != fixed and dests[1].parent != fixed
    for dest in dests:
        assert not dest.exists() and not dest.parent.exists(), "私有临时目录未清理"


def testElevatedCommandBindsHashAndEscapesPath(monkeypatch):
    """提权命令：验签后哈希参与执行前复核；路径单引号转义。"""
    captured: list = []

    class R:
        returncode = 0
        stdout = ""

    def fake_runText(argv, timeout):
        captured.append(list(argv))
        return R()

    monkeypatch.setattr(env_check, "runText", fake_runText)

    digest = "ab" * 32
    exe = Path(r"C:\tmp\o'neil\vc_redist.x64.exe")
    assert env_check._run_elevated_installer(exe, digest) == 0

    script = captured[0][-1]
    assert "Get-FileHash" in script
    assert digest in script
    assert "o''neil" in script, "单引号未按 PowerShell 规则转义"
    assert script.index("Get-FileHash") < script.index("Start-Process"), (
        "哈希复核必须发生在 Start-Process 之前"
    )


@pytest.mark.skipif(sys.platform != "win32", reason="需要真实 PowerShell")
def testRealPowerShellAbortsOnHashMismatchBeforeElevation(tmp_path):
    """真 PowerShell：内容哈希与期望值不符 → 退出 86，不触发 Start-Process/UAC。"""
    exe = tmp_path / "vc_redist.x64.exe"
    exe.write_bytes(b"tampered-after-verification")
    code = env_check._run_elevated_installer(exe, "0" * 64)
    assert code == 86, f"哈希不符却未在提权前中止（exit={code}）"