# -*- coding: utf-8 -*-
"""start.py 依赖检查缺陷回归测试（2026-09-15 前端"启动不起来"事故）

根因：check_node_deps 只判断 node_modules 目录存在——半损坏状态
（.bin 全部丢失/部分包缺失，npm 中断或清理工具所伤）骗过检查，
npm run dev 报 "'vite' 不是内部或外部命令" 且脚本不自愈。

附带：check_python_deps 用当前解释器 import fastapi 检查，但后端实际
跑 venv（_get_backend_python）——检查对象与运行对象错位。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest


@pytest.fixture
def start_mod():
    import start

    return start


class TestCheckNodeDeps:
    def test_half_broken_node_modules_triggers_reinstall(self, start_mod, tmp_path, monkeypatch):
        """目录存在但 .bin/vite 缺失 = 半损坏，必须触发重装（npm ci 优先 lock）"""
        fe = tmp_path / "NeurUI"
        (fe / "node_modules").mkdir(parents=True)  # 目录在，但 .bin 空
        (fe / "package-lock.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(start_mod, "FRONTEND_DIR", fe)
        calls = []
        monkeypatch.setattr(start_mod.subprocess, "run",
                            lambda cmd, **kw: calls.append(cmd))
        start_mod.check_node_deps()
        assert calls, "半损坏 node_modules 必须触发重装，否则 npm run dev 找不到 vite"
        assert "ci" in " ".join(map(str, calls[0])), "有 package-lock 时应 npm ci 干净重装"

    def test_healthy_node_modules_no_reinstall(self, start_mod, tmp_path, monkeypatch):
        fe = tmp_path / "NeurUI"
        binname = "vite.cmd" if sys.platform == "win32" else "vite"
        (fe / "node_modules" / ".bin").mkdir(parents=True)
        (fe / "node_modules" / ".bin" / binname).write_text("", encoding="utf-8")
        monkeypatch.setattr(start_mod, "FRONTEND_DIR", fe)
        calls = []
        monkeypatch.setattr(start_mod.subprocess, "run",
                            lambda cmd, **kw: calls.append(cmd))
        start_mod.check_node_deps()
        assert not calls, "vite 可执行文件在位时不得误触发重装"

    def test_missing_node_modules_falls_back_to_install(self, start_mod, tmp_path, monkeypatch):
        fe = tmp_path / "NeurUI"
        fe.mkdir(parents=True)  # 无 node_modules 无 lock
        monkeypatch.setattr(start_mod, "FRONTEND_DIR", fe)
        calls = []
        monkeypatch.setattr(start_mod.subprocess, "run",
                            lambda cmd, **kw: calls.append(cmd))
        start_mod.check_node_deps()
        assert calls and "install" in " ".join(map(str, calls[0]))


class TestNpmInvocationKeepsArguments:
    """OPS-04：npm 安装命令必须以 argv 形态交给 subprocess，参数不得被 shell 吃掉。

    审计 2026-11-25 批次 E 实测：`subprocess.run(["npm", "ci"], shell=True)` 在
    POSIX 下由 CPython 拼成 `['/bin/sh', '-c', 'npm', 'ci']` —— 只有 argv[0] 被当成
    命令串，`"ci"` 变成 `$0` 被丢掉，npm 无参数运行（退出码 0），锁文件干净安装
    语义静默丢失。Windows 侧因 list2cmdline 拼整串而"恰好正常"，两平台语义分叉。
    """

    @staticmethod
    def _captureInvocation(start_mod, monkeypatch, tmp_path, *, withLock: bool = True):
        fe = tmp_path / "NeurUI"
        fe.mkdir(parents=True)
        if withLock:
            (fe / "package-lock.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(start_mod, "FRONTEND_DIR", fe)
        calls = []

        def fakeRun(cmd, **kw):
            calls.append((cmd, kw))

        monkeypatch.setattr(start_mod.subprocess, "run", fakeRun)
        start_mod.check_node_deps()
        assert calls, "半损坏 node_modules 必须触发重装"
        return calls[0]

    def test_reinstallUsesArgvWithoutShell(self, start_mod, tmp_path, monkeypatch):
        cmd, kwargs = self._captureInvocation(start_mod, monkeypatch, tmp_path)
        assert isinstance(cmd, (list, tuple)), (
            f"npm 命令必须是 argv 序列（实际 {type(cmd).__name__}）——"
            "shell=True + 列表在 POSIX 下只把首项当命令，其余参数被丢掉"
        )
        assert not kwargs.get("shell"), (
            "重装调用仍在用 shell=True：POSIX 下 npm ci 的参数会被 sh -c 吃掉，"
            "Windows 下靠 list2cmdline 侥幸成串——两平台语义分叉（OPS-04）"
        )

    def test_reinstallCarriesCleanInstallFlags(self, start_mod, tmp_path, monkeypatch):
        cmd, _ = self._captureInvocation(start_mod, monkeypatch, tmp_path)
        argv = [str(part) for part in cmd]
        assert "--no-audit" in argv and "--no-fund" in argv, (
            f"npm 干净安装参数缺失（实际 argv={argv}）——两侧必须同参数，"
            "否则一侧装依赖时会卡在无关的网络审计/赞助输出上"
        )

    def test_reinstallResolvesRealNpmExecutable(self, start_mod, tmp_path, monkeypatch):
        """Windows 上 npm 是 npm.CMD：shell=False 必须用 which 解析真实路径。

        裸 `["npm", ...]` 走 CreateProcess 不认 PATHEXT（WinError 2），
        scripts/desktop/win_installer_kit.py 已在实机踩过同一坑。
        """
        resolved = shutil.which("npm")
        if not resolved:
            pytest.skip("本机没有 npm，无法判定可执行文件解析面")
        cmd, _ = self._captureInvocation(start_mod, monkeypatch, tmp_path)
        assert str(cmd[0]) == resolved, (
            f"npm 可执行文件未按 which 解析（实际 {cmd[0]!r}，应为 {resolved!r}）——"
            "Windows 上裸名 + shell=False 会找不到 npm.CMD"
        )

    def test_installFallbackWithoutLockStillArgv(self, start_mod, tmp_path, monkeypatch):
        cmd, kwargs = self._captureInvocation(start_mod, monkeypatch, tmp_path, withLock=False)
        assert "install" in [str(part) for part in cmd]
        assert not kwargs.get("shell")


class TestCheckPythonDeps:
    def test_check_runs_with_backend_interpreter(self, start_mod, monkeypatch, tmp_path):
        """检查必须用 _get_backend_python 选定的解释器（venv 优先），
        而非 sys.executable——否则系统 Python 有 fastapi 就跳过，
        venv 缺依赖照样崩。"""
        fake_venv = tmp_path / "venvpy.exe"
        fake_venv.write_text("", encoding="utf-8")
        monkeypatch.setattr(start_mod, "get_venv_python", lambda: fake_venv)
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            class R:
                returncode = 1  # 假装缺依赖，走安装分支
            return R()

        monkeypatch.setattr(start_mod.subprocess, "run", fake_run)
        start_mod.check_python_deps()
        assert str(fake_venv) in str(seen["cmd"][0]), (
            f"依赖检查应跑在后端解释器上，实际用 {seen['cmd'][0]}"
        )

    def testMissingDepsInstallsManifestSelectedLock(self, start_mod, monkeypatch, tmp_path):
        fakeVenv = tmp_path / "venvpy.exe"
        fakeVenv.write_text("", encoding="utf-8")
        models = tmp_path / "models"
        models.mkdir()
        (models / "MANIFEST.json").write_text(json.dumps({
            "runtime": {"pip": {"requirements": "compiled.lock"}}
        }), encoding="utf-8")
        selectedLock = tmp_path / "compiled.lock"
        selectedLock.write_text("fastapi==0.0.0\n", encoding="utf-8")
        monkeypatch.setattr(start_mod, "ROOT_DIR", tmp_path)
        monkeypatch.setattr(start_mod, "get_venv_python", lambda: fakeVenv)
        commands = []

        def fakeRun(cmd, **kwargs):
            commands.append(cmd)
            return type("Result", (), {"returncode": 1 if len(commands) == 1 else 0})()

        monkeypatch.setattr(start_mod.subprocess, "run", fakeRun)

        assert start_mod.check_python_deps(), "缺依赖分支未完成安装"
        assert len(commands) == 2, f"探针与安装命令不完整: {commands}"
        assert commands[1][-2:] == ["-r", str(selectedLock)], (
            f"启动器未按 MANIFEST 选择完整锁: {commands[1]}"
        )
