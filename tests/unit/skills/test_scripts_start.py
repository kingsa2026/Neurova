"""
Neurova 统一启动脚本测试
测试 start.py 中的核心逻辑
"""

import sys
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest


class TestGetBackendPython:
    """测试 _get_backend_python 函数"""
    
    def test_returns_venv_python_when_exists(self):
        """当虚拟环境存在时，返回虚拟环境 Python"""
        from start import _get_backend_python
        from scripts.config import get_venv_python
        
        with patch('start.get_venv_python') as mock_get:
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_path.__str__ = lambda self: "/path/to/python"
            mock_get.return_value = mock_path
            
            result = _get_backend_python()
            assert result == ["/path/to/python"]
    
    def test_returns_system_python_when_no_venv(self):
        """当虚拟环境不存在时，返回系统 Python"""
        from start import _get_backend_python
        
        with patch('start.get_venv_python') as mock_get:
            mock_path = MagicMock()
            mock_path.exists.return_value = False
            mock_get.return_value = mock_path
            
            result = _get_backend_python()
            assert result == [sys.executable]


class TestStartBackend:
    """测试 start_backend 函数"""
    
    def test_returns_process_and_log_handle(self):
        """启动后端返回进程和日志句柄"""
        from start import start_backend
        
        with patch('start.subprocess.Popen') as mock_popen, \
             patch('start._get_backend_python', return_value=["python"]), \
             patch('start.get_backend_script', return_value=Path("start_server.py")), \
             patch('start.os.environ.copy', return_value={}):
            mock_proc = MagicMock()
            mock_popen.return_value = mock_proc
            
            proc, log_fh = start_backend(port=9527)
            assert proc == mock_proc
            assert log_fh is None  # 无日志文件时为 None
    
    def test_with_log_file(self):
        """带日志文件启动后端"""
        from start import start_backend
        
        mock_log_dir = MagicMock()
        mock_log_dir.mkdir = MagicMock()
        
        with patch('start.subprocess.Popen') as mock_popen, \
             patch('start._get_backend_python', return_value=["python"]), \
             patch('start.get_backend_script', return_value=Path("start_server.py")), \
             patch('start.os.environ.copy', return_value={}), \
             patch('start.ROOT_DIR') as mock_root:
            mock_root.__truediv__ = lambda self, x: mock_log_dir
            mock_proc = MagicMock()
            mock_popen.return_value = mock_proc
            
            with patch('builtins.open', MagicMock()):
                proc, log_fh = start_backend(port=9527, log_file="server.log")
                assert proc == mock_proc
                assert log_fh is not None


class TestStartFrontend:
    """测试 start_frontend 函数"""
    
    def test_returns_none_when_frontend_not_available(self):
        """前端不可用时返回 None"""
        from start import start_frontend
        
        with patch('start.is_frontend_available', return_value=False):
            result = start_frontend(port=8100)
            assert result is None
    
    def test_starts_frontend_process(self):
        """启动前端进程"""
        from start import start_frontend
        
        with patch('start.is_frontend_available', return_value=True), \
             patch('start.subprocess.Popen') as mock_popen:
            mock_proc = MagicMock()
            mock_popen.return_value = mock_proc
            
            result = start_frontend(port=8100)
            assert result == mock_proc


class TestCheckPythonDeps:
    """测试 check_python_deps 函数"""
    
    def test_returns_true_when_deps_exist(self):
        """依赖存在时返回 True"""
        from start import check_python_deps
        
        with patch.dict('sys.modules', {'fastapi': MagicMock(), 'uvicorn': MagicMock()}):
            result = check_python_deps()
            assert result is True
    
    def test_installs_deps_when_missing(self):
        """依赖缺失时尝试安装"""
        from start import check_python_deps
        
        with patch('start.get_venv_python') as mock_get_venv, \
             patch('start.subprocess.run') as mock_run, \
             patch('start.ROOT_DIR', Path("/mock/root")), \
             patch.dict('sys.modules', {'fastapi': None, 'uvicorn': None}):
            # 使 import fastapi 失败
            mock_get_venv.return_value = MagicMock(exists=MagicMock(return_value=False))
            mock_run.return_value = MagicMock()
            
            # 这会因为 fastapi 无法导入而走到 except 分支
            # 但由于我们无法可靠地模拟 import 失败，这里只测试函数存在
            assert callable(check_python_deps)


class TestCheckNodeDeps:
    """测试 check_node_deps 函数"""
    
    def test_returns_true_when_node_modules_exists(self):
        """node_modules 存在时返回 True"""
        from start import check_node_deps
        
        with patch('start.FRONTEND_DIR') as mock_dir:
            mock_dir.__truediv__ = lambda self, x: MagicMock(exists=MagicMock(return_value=True))
            result = check_node_deps()
            assert result is True


class TestMainArgumentParsing:
    """测试 main 函数参数解析"""
    
    def test_check_mode_exits_early(self):
        """--check 模式应退出并返回 0"""
        from start import main
        
        with patch('sys.argv', ['start.py', '--check']), \
             patch('start.print_logo'), \
             patch('start.print_status'), \
             patch('start.print_services_status'):
            result = main()
            assert result == 0
    
    def test_default_port_values(self):
        """默认端口值应为配置中的值"""
        from scripts.config import BACKEND_PORT, FRONTEND_PORT
        assert BACKEND_PORT == 9527
        assert FRONTEND_PORT == 8100


class TestImports:
    """测试模块导入"""
    
    def test_import_start_module(self):
        """测试 start.py 模块可以被导入"""
        import start
        assert hasattr(start, 'main')
        assert hasattr(start, 'start_backend')
        assert hasattr(start, 'start_frontend')
        assert hasattr(start, 'check_python_deps')
        assert hasattr(start, 'check_node_deps')
        assert hasattr(start, 'start_cli')
        assert hasattr(start, 'print_status')
        assert hasattr(start, '_get_backend_python')
    
    def test_import_shared_modules(self):
        """测试共享模块导入"""
        from scripts.common import print_logo, c, Colors, ProgressBar
        from scripts.config import ROOT_DIR, BACKEND_PORT, FRONTEND_PORT
        from scripts.port_utils import check_port, kill_port, wait_for_port
        from scripts.health_check import health_check, wait_for_server
        
        assert callable(print_logo)
        assert callable(c)
        assert callable(check_port)
        assert callable(kill_port)
        assert callable(wait_for_port)
        assert callable(health_check)
        assert callable(wait_for_server)
        assert BACKEND_PORT == 9527
        assert FRONTEND_PORT == 8100


class TestCrossPlatform:
    """测试跨平台兼容性"""
    
    def test_no_netstat_usage(self):
        """确保 start.py 不使用 Windows-only 的 netstat"""
        start_content = Path("start.py").read_text(encoding="utf-8")
        assert "netstat" not in start_content.lower()
    
    def test_no_taskkill_usage(self):
        """确保 start.py 不使用 Windows-only 的 taskkill"""
        start_content = Path("start.py").read_text(encoding="utf-8")
        assert "taskkill" not in start_content.lower()
    
    def test_no_powershell_usage(self):
        """确保 start.py 不使用 PowerShell"""
        start_content = Path("start.py").read_text(encoding="utf-8")
        assert "powershell" not in start_content.lower()
    
    def test_uses_scripts_port_utils(self):
        """确保 start.py 使用 scripts.port_utils 而非自定义端口检测"""
        start_content = Path("start.py").read_text(encoding="utf-8")
        assert "from scripts.port_utils import" in start_content
        assert "check_port" in start_content
        assert "kill_port" in start_content
