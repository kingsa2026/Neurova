"""check_dependencies 防回归测试（start.py 闪退根因，2026-09-16）

事故：PATH 上 python=3.15.0a7，其 Pillow 12.3.0 cp315 二进制与该 alpha 的
ABI 不匹配，import pyautogui 链上 PIL._imaging 抛
SystemError("module PIL._imaging uses unknown slot ID 85")。
旧版 check_dependencies 在拉起脚本的解释器内 __import__ 且只捕 ImportError，
SystemError 穿透 → python start.py --check / --restart / 双服务在跑时的默认
模式直接闪退。

根因两层：
1) 检查对象与运行对象错位——被检的是后端（venv）的包，检查却发生在宿主解释器；
2) 异常面过窄——ABI 损坏的 C 扩展 import 时抛的不是 ImportError。
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import scripts.health_check as hc


# 模拟 ABI 损坏的二进制包：import 即抛 SystemError（事故原文）
_BROKEN_MODULE = (
    "raise SystemError("
    "'module PIL._imaging uses unknown slot ID 85')\n"
)


@pytest.fixture(autouse=True)
def _fresh_cache():
    """每个用例从空缓存开始，避免解释器级缓存串扰探测行为断言。"""
    hc._deps_cache.clear()
    yield
    hc._deps_cache.clear()


class _FakeCompleted:
    def __init__(self, cmd, stdout=""):
        self.args = cmd
        self.returncode = 0
        self.stdout = stdout
        self.stderr = ""


class TestNoCrashOnBrokenDependency:
    """核心回归：任何包 import 炸出非 ImportError 异常，都只记不可用，不得抛出"""

    def test_system_error_on_import_does_not_crash(self, tmp_path, monkeypatch):
        pkg_dir = tmp_path / "pyautogui"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text(_BROKEN_MODULE, encoding="utf-8")
        # 子进程视角走 PYTHONPATH 遮蔽；进程内视角走 sys.path 遮蔽
        # （旧版在当前解释器 __import__，sys.path 遮蔽即复现 SystemError 穿透）
        monkeypatch.setenv("PYTHONPATH", str(tmp_path))
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setattr(hc, "_DEPENDENCIES_TO_PROBE", ("pyautogui",))

        result = hc.check_dependencies()  # 旧版此处抛 SystemError → 闪退

        assert result == {"pyautogui": False}

    def test_subprocess_failure_returns_all_false(self, monkeypatch):
        def boom(cmd, **kwargs):
            raise OSError("interpreter disappeared")

        monkeypatch.setattr(hc.subprocess, "run", boom)
        monkeypatch.setattr(hc, "_DEPENDENCIES_TO_PROBE", ("fastapi", "PIL"))

        result = hc.check_dependencies()

        assert result == {"fastapi": False, "PIL": False}


class TestProbesBackendInterpreter:
    """探测必须发生在真正跑后端的解释器上，而非拉起脚本的解释器"""

    def test_uses_venv_python_when_available(self, tmp_path, monkeypatch):
        fake_venv = tmp_path / "python.exe"
        fake_venv.write_text("", encoding="utf-8")
        monkeypatch.setattr(hc, "get_venv_python", lambda: fake_venv)

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            mods = cmd[3:]
            return _FakeCompleted(cmd, "x" + hc._DEPS_MARKER + json.dumps(
                {m: True for m in mods}))

        monkeypatch.setattr(hc.subprocess, "run", fake_run)

        result = hc.check_dependencies()

        assert calls, "check_dependencies 未起子进程探测"
        cmd, kwargs = calls[0]
        assert cmd[0] == str(fake_venv)
        assert kwargs.get("shell") is not True, "探测不得经 shell 拼接"
        assert all(v is True for v in result.values())

    def test_falls_back_to_current_interpreter_without_venv(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            hc, "get_venv_python", lambda: tmp_path / "nope" / "python.exe")

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _FakeCompleted(cmd, "noise\n" + hc._DEPS_MARKER + json.dumps(
                {m: False for m in cmd[3:]}))

        monkeypatch.setattr(hc.subprocess, "run", fake_run)

        result = hc.check_dependencies()

        assert calls[0][0] == sys.executable
        assert all(v is False for v in result.values())

    def test_result_cached_per_interpreter(self, tmp_path, monkeypatch):
        fake_venv = tmp_path / "python.exe"
        fake_venv.write_text("", encoding="utf-8")
        monkeypatch.setattr(hc, "get_venv_python", lambda: fake_venv)

        runs = []

        def fake_run(cmd, **kwargs):
            runs.append(cmd)
            return _FakeCompleted(cmd, hc._DEPS_MARKER + json.dumps(
                {m: True for m in cmd[3:]}))

        monkeypatch.setattr(hc.subprocess, "run", fake_run)

        hc.check_dependencies()
        hc.check_dependencies()

        assert len(runs) == 1, "同解释器重复调用不应重复全量 import 探测"


class TestContractPreserved:
    """dict[str, bool] 契约与体检覆盖面不变"""

    def test_default_probe_list_covers_backend_and_computer_use(self):
        assert set(hc._DEPENDENCIES_TO_PROBE) == {
            "fastapi", "uvicorn", "sentence_transformers",
            "PIL", "pyautogui", "playwright",
        }


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
