"""
环境预检模块契约（torch c10.dll WinError 1114 → VC++ 运行库自动装）

背景：2026-09-04 安装版日志显示干净机器上 torch/lib/c10.dll 初始化失败
（WinError 1114），典型根因是目标机缺 VC++ 2015-2022 x64 运行库。
契约（全部可注入桩，测试不发真实网络请求/不拉起子进程/不读真实注册表）：

- detect_torch_dll_problem(): torch 导入失败且为 DLL 初始化错误 → 返回
  TorchDllProblem；导入成功 → None；其他导入异常不误报
- is_vc_redist_installed(): 注册表 Runtimes\\x64 Installed=1 → True；
  键缺失 → False；非 Windows → True（不处理）
- ensure_vc_redist(): 检测缺失才下载官方 aka.ms 固定 URL 并提权静默安装；
  已装/非 Windows/关闭 auto_install → 不下载不安装；返回动作结果
- preflight_torch_runtime(): 编排入口，任何失败只告警不阻断启动
"""
import os
import subprocess
import sys
from unittest import mock

import pytest

from neurova.core import env_check


def _dll_error():
    return OSError(1114, "动态链接库(DLL)初始化例程失败。")


class TestDetectTorchDllProblem:
    def test_import_ok_returns_none(self, monkeypatch):
        monkeypatch.setattr(env_check, "_import_torch", lambda: object())
        assert env_check.detect_torch_dll_problem() is None

    def test_dll_init_failure_detected(self, monkeypatch):
        def boom():
            raise _dll_error()

        monkeypatch.setattr(env_check, "_import_torch", boom)
        problem = env_check.detect_torch_dll_problem()
        assert problem is not None
        assert problem.winerror == 1114

    def test_other_import_error_not_reported_as_dll(self, monkeypatch):
        def boom():
            raise ImportError("No module named 'torch'")

        monkeypatch.setattr(env_check, "_import_torch", boom)
        assert env_check.detect_torch_dll_problem() is None


class TestVcRedistDetection:
    def test_registry_installed_true(self, monkeypatch):
        monkeypatch.setattr(env_check, "_read_vc_runtime_version", lambda: "14.38.33130.00")
        assert env_check.is_vc_redist_installed() is True

    def test_registry_missing_false(self, monkeypatch):
        monkeypatch.setattr(env_check, "_read_vc_runtime_version", lambda: None)
        assert env_check.is_vc_redist_installed() is False

    def test_old_version_below_2022_false(self, monkeypatch):
        monkeypatch.setattr(env_check, "_read_vc_runtime_version", lambda: "14.16.27012.06")
        assert env_check.is_vc_redist_installed() is False

    def test_non_windows_always_true(self, monkeypatch):
        monkeypatch.setattr(env_check, "_IS_WINDOWS", False)
        monkeypatch.setattr(env_check, "_read_vc_runtime_version", lambda: None)
        assert env_check.is_vc_redist_installed() is True


class TestEnsureVcRedist:
    def _noop_download(self, calls, url, dest):
        calls.append(("download", url, dest))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(b"MZ fake")

    def test_missing_runtime_triggers_download_and_install(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(env_check, "_IS_WINDOWS", True)
        monkeypatch.setattr(env_check, "_read_vc_runtime_version", lambda: None)
        monkeypatch.setattr(
            env_check, "_download_file", lambda url, dest: self._noop_download(calls, url, dest)
        )
        monkeypatch.setattr(env_check, "_verify_authenticode", lambda exe: True)
        monkeypatch.setattr(
            env_check, "_run_elevated_installer", lambda exe: calls.append(("install", exe)) or 0
        )
        result = env_check.ensure_vc_redist(auto_install=True, download_dir=tmp_path)
        assert result.installed is True
        kinds = [c[0] for c in calls]
        assert kinds == ["download", "install"]
        # 必须是官方 aka.ms 固定 URL
        assert calls[0][1] == env_check.VC_REDIST_URL

    def test_runtime_present_noop(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(env_check, "_IS_WINDOWS", True)
        monkeypatch.setattr(env_check, "_read_vc_runtime_version", lambda: "14.38.33130.00")
        monkeypatch.setattr(
            env_check,
            "_download_file",
            lambda url, dest: self._noop_download(calls, url, dest),
        )
        result = env_check.ensure_vc_redist(auto_install=True, download_dir=tmp_path)
        assert result.installed is False
        assert result.reason == "already-installed"
        assert calls == []

    def test_auto_install_off_noop(self, tmp_path, monkeypatch):
        monkeypatch.setattr(env_check, "_IS_WINDOWS", True)
        monkeypatch.setattr(env_check, "_read_vc_runtime_version", lambda: None)
        result = env_check.ensure_vc_redist(auto_install=False, download_dir=tmp_path)
        assert result.installed is False
        assert result.reason == "auto-install-off"

    def test_non_windows_noop(self, tmp_path, monkeypatch):
        monkeypatch.setattr(env_check, "_IS_WINDOWS", False)
        result = env_check.ensure_vc_redist(auto_install=True, download_dir=tmp_path)
        assert result.installed is False
        assert result.reason == "not-windows"

    def test_download_failure_surfaces_reason(self, tmp_path, monkeypatch):
        def bad_download(url, dest):
            raise OSError("network down")

        monkeypatch.setattr(env_check, "_IS_WINDOWS", True)
        monkeypatch.setattr(env_check, "_read_vc_runtime_version", lambda: None)
        monkeypatch.setattr(env_check, "_download_file", bad_download)
        result = env_check.ensure_vc_redist(auto_install=True, download_dir=tmp_path)
        assert result.installed is False
        assert "network down" in result.reason

    def test_installer_failure_exit_code(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(env_check, "_IS_WINDOWS", True)
        monkeypatch.setattr(env_check, "_read_vc_runtime_version", lambda: None)
        monkeypatch.setattr(
            env_check, "_download_file", lambda url, dest: self._noop_download(calls, url, dest)
        )
        monkeypatch.setattr(env_check, "_verify_authenticode", lambda exe: True)
        monkeypatch.setattr(env_check, "_run_elevated_installer", lambda exe: 1638)
        result = env_check.ensure_vc_redist(auto_install=True, download_dir=tmp_path)
        assert result.installed is False
        assert "exit=1638" in result.reason


class TestTorchImportsOk:
    def test_subprocess_ok(self, monkeypatch):
        monkeypatch.setattr(
            env_check,
            "subprocess",
            mock.Mock(
                **{
                    "run.return_value": subprocess.CompletedProcess([], 0, stdout="", stderr=""),
                }
            ),
        )
        assert env_check.torch_imports_ok(sys.executable) is True

    def test_subprocess_fail(self, monkeypatch):
        monkeypatch.setattr(
            env_check,
            "subprocess",
            mock.Mock(
                **{
                    "run.return_value": subprocess.CompletedProcess([], 1, stdout="", stderr="err"),
                }
            ),
        )
        assert env_check.torch_imports_ok(sys.executable) is False


class TestPreflightOrchestration:
    def test_healthy_noop(self, monkeypatch, caplog):
        monkeypatch.setattr(env_check, "detect_torch_dll_problem", lambda: None)
        monkeypatch.setattr(env_check, "ensure_vc_redist", mock.Mock())
        env_check.preflight_torch_runtime()
        env_check.ensure_vc_redist.assert_not_called()

    def test_dll_problem_and_missing_runtime_installs(self, monkeypatch):
        problem = env_check.TorchDllProblem(winerror=1114, dll="c10.dll")
        monkeypatch.setattr(env_check, "detect_torch_dll_problem", lambda: problem)
        ensured = env_check.EnsureResult(installed=True, reason="ok")
        monkeypatch.setattr(env_check, "ensure_vc_redist", mock.Mock(return_value=ensured))
        monkeypatch.setattr(env_check, "torch_imports_ok", mock.Mock(return_value=True))
        env_check.preflight_torch_runtime()
        env_check.ensure_vc_redist.assert_called_once()
        env_check.torch_imports_ok.assert_called_once()

    def test_install_fail_does_not_raise(self, monkeypatch):
        problem = env_check.TorchDllProblem(winerror=1114, dll="c10.dll")
        monkeypatch.setattr(env_check, "detect_torch_dll_problem", lambda: problem)
        failed = env_check.EnsureResult(installed=False, reason="exit=5100")
        monkeypatch.setattr(env_check, "ensure_vc_redist", mock.Mock(return_value=failed))
        monkeypatch.setattr(env_check, "torch_imports_ok", mock.Mock(return_value=False))
        # 不抛异常 = 不阻断启动
        env_check.preflight_torch_runtime()

    def test_never_raises_unexpected(self, monkeypatch):
        def boom():
            raise RuntimeError("unexpected")

        monkeypatch.setattr(env_check, "detect_torch_dll_problem", boom)
        env_check.preflight_torch_runtime()  # 不抛
