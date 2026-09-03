"""start.py 启动脚本回归测试。

锁定三个历史 bug（S-1/S-2/S-3）防止复发：
- S-1: restart_services 在"无运行服务直接启动"分支引用未定义的 processes → NameError
- S-3: start.bat 传递的 --yes 参数未在 argparse 定义 → exit code 2
- 附带验证 --force-restart 与 -y 别名可解析
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
START_PY = REPO_ROOT / "start.py"

# 将项目根加入 sys.path 以便 import start
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestStartArgParsing(unittest.TestCase):
    """S-3 回归：bat 传入的参数必须能被 argparse 接受。"""

    def _run_check(self, *extra) -> int:
        proc = subprocess.run(
            [sys.executable, str(START_PY), "--skip-install", "--check", *extra],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return proc.returncode

    def test_yes_flag_accepted(self):
        self.assertEqual(self._run_check("--yes"), 0)

    def test_y_short_alias_accepted(self):
        self.assertEqual(self._run_check("-y"), 0)

    def test_force_restart_flag_exists_in_help(self):
        proc = subprocess.run(
            [sys.executable, str(START_PY), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertIn("--force-restart", proc.stdout)


class TestRestartServicesNoRunningBranch(unittest.TestCase):
    """S-1 回归：服务全未运行时走"直接启动"分支不再 NameError。"""

    def _patched_restart(self):
        import start as start_module

        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_services = {
            "backend": {"port": 9527, "occupied": False, "healthy": False},
            "frontend": {"port": 8100, "occupied": False},
            "dependencies": {},
        }
        with patch.object(start_module, "check_all_services", return_value=fake_services), \
             patch.object(start_module, "check_python_deps", return_value=True), \
             patch.object(start_module, "check_node_deps", return_value=True), \
             patch.object(start_module, "start_backend",
                          return_value=(fake_proc, MagicMock())), \
             patch.object(start_module, "wait_for_server", return_value=True), \
             patch.object(start_module, "start_frontend", return_value=MagicMock()):
            rc = start_module.restart_services(auto_yes=True)
        return rc

    def test_no_nameerror_and_starts_both(self):
        rc = self._patched_restart()
        self.assertEqual(rc, 0)

    def test_backend_only_restart(self):
        # restart_frontend=False 时不应调用 start_frontend
        import start as start_module

        fake_services = {
            "backend": {"port": 9527, "occupied": False, "healthy": False},
            "frontend": {"port": 8100, "occupied": False},
            "dependencies": {},
        }
        with patch.object(start_module, "check_all_services", return_value=fake_services), \
             patch.object(start_module, "check_python_deps", return_value=True), \
             patch.object(start_module, "check_node_deps", return_value=True) as node_deps, \
             patch.object(start_module, "start_backend",
                          return_value=(MagicMock(), MagicMock())), \
             patch.object(start_module, "wait_for_server", return_value=True), \
             patch.object(start_module, "start_frontend", return_value=MagicMock()) as fe:
            rc = start_module.restart_services(
                restart_backend=True, restart_frontend=False, auto_yes=True
            )
        self.assertEqual(rc, 0)
        fe.assert_not_called()
        node_deps.assert_not_called()


class TestRestartConfirmSkip(unittest.TestCase):
    """auto_yes=True 跳过交互确认（提权窗口无 stdin 也不会挂起）。"""

    def test_auto_yes_skips_input(self):
        import builtins
        import start as start_module

        fake_services = {
            "backend": {"port": 9527, "occupied": True, "healthy": True},
            "frontend": {"port": 8100, "occupied": True},
            "dependencies": {},
        }
        input_calls = []
        real_input = builtins.input

        def fake_input(prompt=""):
            input_calls.append(prompt)
            raise AssertionError("auto_yes 模式不应调用 input()")

        with patch.object(start_module, "check_all_services", return_value=fake_services), \
             patch.object(start_module, "kill_port"), \
             patch.object(start_module, "wait_for_port_free"), \
             patch.object(start_module, "check_python_deps", return_value=True), \
             patch.object(start_module, "check_node_deps", return_value=True), \
             patch.object(start_module, "start_backend",
                          return_value=(MagicMock(), MagicMock())), \
             patch.object(start_module, "wait_for_server", return_value=True), \
             patch.object(start_module, "start_frontend", return_value=MagicMock()), \
             patch("builtins.input", side_effect=fake_input):
            rc = start_module.restart_services(auto_yes=True)

        self.assertEqual(rc, 0)
        self.assertEqual(input_calls, [])


if __name__ == "__main__":
    unittest.main()
