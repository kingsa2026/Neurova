"""
Neurova 启动脚本 bug 测试 v1
测试 start.py 中发现的关键 bug
"""

import sys
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest


# ═══════════════════════════════════════════════════════════════
# S-1: restart_services 中 processes 未定义 → NameError
# ═══════════════════════════════════════════════════════════════

class TestS1RestartServicesProcessesUndefined:
    """Bug S-1: restart_services 函数在"没有需要停止的服务"分支引用 processes 变量，
    但该变量在 restart_services 作用域内未定义（只有 main 函数 line 598 有 processes = []）。

    触发条件:
        - 调用 restart_services(restart_frontend=True)
        - check_all_services() 返回前端未占用（need_stop_frontend=False）
        - 进入 line 268 "没有需要停止的服务" 分支
        - line 284: processes.append(("Frontend", proc, None)) → NameError

    后果: 一键重启时如果服务未运行，直接崩溃，无法启动。
    """

    def test_restart_services_no_nameerror_when_no_running_services(self):
        """restart_services 在无运行服务时不应抛 NameError。"""
        from start import restart_services

        # 模拟: 后端/前端都未运行（need_stop_backend=False, need_stop_frontend=False）
        # 这样会进入 line 268 "没有需要停止的服务" 分支
        mock_services = {
            "backend": {"occupied": False, "port": 9527},
            "frontend": {"occupied": False, "port": 8100},
        }

        with patch('start.check_all_services', return_value=mock_services), \
             patch('start.check_python_deps'), \
             patch('start.check_node_deps'), \
             patch('start.start_backend') as mock_start_backend, \
             patch('start.start_frontend') as mock_start_frontend, \
             patch('start.wait_for_server', return_value=True), \
             patch('start.time.sleep'):
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_start_backend.return_value = (mock_proc, None)
            mock_start_frontend.return_value = mock_proc

            # 不应抛出 NameError
            try:
                result = restart_services(
                    restart_backend=True,
                    restart_frontend=True,
                    auto_yes=True,
                )
                # 应正常返回 0
                assert result == 0, f"restart_services 应返回 0，实际: {result}"
            except NameError as e:
                pytest.fail(
                    f"restart_services 在无运行服务时抛出 NameError: {e}。"
                    f"原因是函数作用域内 processes 变量未定义。"
                )


# ═══════════════════════════════════════════════════════════════
# S-2: taskkill /F /IM node.exe 杀全部 node 进程 + 违反跨平台规范
# ═══════════════════════════════════════════════════════════════

class TestS2TaskkillAllNodeProcesses:
    """Bug S-2: restart_services line 320-325 执行 `taskkill /F /IM node.exe`，
    会杀掉系统上所有 node.exe 进程（包括 VSCode、其他 dev server、Discord 等）。

    同时违反项目跨平台规范:
    - TestCrossPlatform::test_no_taskkill_usage 已断言 start.py 不应包含 "taskkill"
    - 该测试当前失败（start.py 包含 taskkill）

    修复方向: 使用 port_utils.kill_port(frontend_port) 精准释放端口，
    不再杀全部 node 进程。
    """

    def test_start_py_does_not_contain_taskkill(self):
        """start.py 不应包含 taskkill 命令（违反跨平台规范）。"""
        start_content = Path("start.py").read_text(encoding="utf-8")
        assert "taskkill" not in start_content.lower(), (
            "start.py 不应直接调用 taskkill（Windows-only + 危险），"
            "应使用 scripts/port_utils.py 的 kill_port 跨平台释放端口"
        )

    def test_start_py_does_not_contain_node_exe_kill(self):
        """start.py 不应包含杀掉所有 node.exe 的命令。"""
        start_content = Path("start.py").read_text(encoding="utf-8").lower()
        # 检查是否还有 "node.exe" + "kill" 组合
        assert '"/im", "node.exe"' not in start_content, (
            "start.py 不应执行 taskkill /IM node.exe 杀掉所有 node 进程，"
            "这会误杀 VSCode、其他 dev server 等无关进程"
        )
        assert 'node.exe' not in start_content, (
            "start.py 不应包含 node.exe 字样（杀全部 node 进程的命令）"
        )

    def test_restart_services_uses_kill_port_for_frontend(self):
        """restart_services 应通过 kill_port(frontend_port) 释放前端端口，
        而非 taskkill /IM node.exe。"""
        from start import restart_services

        # 模拟前端端口被占用（需要停止）
        mock_services = {
            "backend": {"occupied": False, "port": 9527},
            "frontend": {"occupied": True, "port": 8100},
        }

        taskkill_calls = []

        def capture_taskkill(*args, **kwargs):
            # 记录所有 taskkill 调用
            if args and isinstance(args[0], list) and "taskkill" in args[0]:
                taskkill_calls.append(args[0])
            return MagicMock(returncode=0)

        with patch('start.check_all_services', return_value=mock_services), \
             patch('start.check_python_deps'), \
             patch('start.check_node_deps'), \
             patch('start.kill_port') as mock_kill_port, \
             patch('start.wait_for_port_free', return_value=True), \
             patch('start.start_backend') as mock_start_backend, \
             patch('start.start_frontend') as mock_start_frontend, \
             patch('start.wait_for_server', return_value=True), \
             patch('start.subprocess.run', side_effect=capture_taskkill), \
             patch('start.time.sleep'):
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_start_backend.return_value = (mock_proc, None)
            mock_start_frontend.return_value = mock_proc

            restart_services(
                restart_backend=False,
                restart_frontend=True,
                auto_yes=True,
            )

            # 应调用 kill_port(frontend_port) 释放端口
            mock_kill_port.assert_any_call(8100)

            # 不应调用 taskkill /IM node.exe
            for call in taskkill_calls:
                assert "node.exe" not in call, (
                    f"不应调用 taskkill /IM node.exe 杀全部 node 进程，"
                    f"实际调用: {call}"
                )


# ═══════════════════════════════════════════════════════════════
# S-3: 缺少 --force-restart 强制重启选项
# ═══════════════════════════════════════════════════════════════

class TestS3ForceRestartOption:
    """Bug S-3: 用户要求"含强制重启"，但当前 --restart 默认交互式确认。
    --yes 可跳过确认，但语义不清晰。应添加 --force-restart 显式强制重启选项。
    """

    def test_force_restart_argument_exists(self):
        """main 函数应支持 --force-restart 参数。"""
        start_content = Path("start.py").read_text(encoding="utf-8")
        assert "--force-restart" in start_content, (
            "start.py 应支持 --force-restart 参数，用于强制重启（跳过确认 + 强制释放端口）"
        )

    def test_force_restart_skips_confirmation(self):
        """--force-restart 应跳过交互式确认（等价于 auto_yes=True）。"""
        from start import main

        # 模拟 --force-restart
        with patch('sys.argv', ['start.py', '--force-restart', '--skip-install']), \
             patch('start.print_logo'), \
             patch('start.check_environment', return_value=True), \
             patch('start.restart_services') as mock_restart:
            mock_restart.return_value = 0

            main()

            # restart_services 应被调用，且 auto_yes=True
            mock_restart.assert_called_once()
            _, kwargs = mock_restart.call_args
            assert kwargs.get('auto_yes') is True, (
                f"--force-restart 应传递 auto_yes=True 跳过确认，"
                f"实际 kwargs: {kwargs}"
            )


# ═══════════════════════════════════════════════════════════════
# S-4: start_backend 不支持 log_file=None
# ═══════════════════════════════════════════════════════════════

class TestS4StartBackendLogNone:
    """Bug S-4: start_backend 默认 log_file="server.log"，总是打开日志文件。
    但测试 test_returns_process_and_log_handle 期望无 log_file 时返回 None。

    修复方向: 支持 log_file=None，此时不打开文件，返回 (proc, None)。
    """

    def test_start_backend_supports_log_file_none(self):
        """start_backend(log_file=None) 应返回 (proc, None)，不打开日志文件。"""
        from start import start_backend

        with patch('start.subprocess.Popen') as mock_popen, \
             patch('start._get_backend_python', return_value=["python"]), \
             patch('start.get_backend_script', return_value=Path("start_server.py")), \
             patch('start.os.environ.copy', return_value={}):
            mock_proc = MagicMock()
            mock_popen.return_value = mock_proc

            proc, log_fh = start_backend(port=9527, log_file=None)
            assert proc == mock_proc
            assert log_fh is None, (
                f"log_file=None 时应返回 None，实际: {log_fh}。"
                f"start_backend 应支持 log_file=None 不打开日志文件。"
            )

    def test_start_backend_with_log_file_returns_handle(self, tmp_path):
        """start_backend(log_file='server.log') 应返回 (proc, file_handle)。"""
        from start import start_backend

        # 用真实临时目录作为 ROOT_DIR，避免 mkdir 失败
        with patch('start.subprocess.Popen') as mock_popen, \
             patch('start._get_backend_python', return_value=["python"]), \
             patch('start.get_backend_script', return_value=Path("start_server.py")), \
             patch('start.os.environ.copy', return_value={}), \
             patch('start.ROOT_DIR', tmp_path), \
             patch('builtins.open', MagicMock()) as mock_open:
            mock_proc = MagicMock()
            mock_popen.return_value = mock_proc
            mock_file = MagicMock()
            mock_open.return_value = mock_file

            proc, log_fh = start_backend(port=9527, log_file="server.log")
            assert proc == mock_proc
            assert log_fh is mock_file, (
                f"log_file='server.log' 时应返回文件句柄，实际: {log_fh}"
            )
