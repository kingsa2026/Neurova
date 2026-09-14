# -*- coding: utf-8 -*-
"""start.py 依赖检查缺陷回归测试（2026-09-15 前端"启动不起来"事故）

根因：check_node_deps 只判断 node_modules 目录存在——半损坏状态
（.bin 全部丢失/部分包缺失，npm 中断或清理工具所伤）骗过检查，
npm run dev 报 "'vite' 不是内部或外部命令" 且脚本不自愈。

附带：check_python_deps 用当前解释器 import fastapi 检查，但后端实际
跑 venv（_get_backend_python）——检查对象与运行对象错位。
"""
from __future__ import annotations

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
