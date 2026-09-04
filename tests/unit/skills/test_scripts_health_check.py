"""
Neurova 健康检查模块测试
测试 health_check.py 中的健康检查、服务器等待、日志监控等功能
"""

import sys
import time
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

# 导入被测模块
from scripts.health_check import (
    health_check, wait_for_server, check_server_ready,
    print_server_status, monitor_server_health, get_server_logs,
    print_server_logs, clear_server_logs, wait_for_server_with_progress,
    check_dependencies, print_dependencies_status, check_all_services,
    print_services_status
)


class TestHealthCheck:
    """测试健康检查"""
    
    def test_health_check_returns_bool(self):
        """测试 health_check 返回布尔值"""
        result = health_check()
        assert isinstance(result, bool)
    
    @patch('urllib.request.urlopen')
    def test_health_check_success(self, mock_urlopen):
        """测试健康检查成功"""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_response)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        
        result = health_check()
        assert result == True
    
    @patch('urllib.request.urlopen', side_effect=Exception("Connection failed"))
    def test_health_check_failure(self, mock_urlopen):
        """测试健康检查失败"""
        result = health_check()
        assert result == False
    
    def test_health_check_custom_port(self):
        """测试自定义端口健康检查"""
        # 这个测试可能失败，因为端口可能没有服务
        # 但函数应该不会抛出异常
        result = health_check(port=9999)
        assert isinstance(result, bool)


class TestWaitForServer:
    """测试等待服务器"""
    
    @patch('scripts.health_check.health_check', return_value=True)
    def test_wait_for_server_immediate_success(self, mock_health_check):
        """测试服务器立即就绪"""
        result = wait_for_server(timeout=5, check_log=False)
        assert result == True
    
    @patch('scripts.health_check.health_check', return_value=False)
    def test_wait_for_server_timeout(self, mock_health_check):
        """测试服务器启动超时"""
        result = wait_for_server(timeout=1, interval=0.1, check_log=False)
        assert result == False
    
    @patch('scripts.health_check.health_check')
    def test_wait_for_server_progress_callback(self, mock_health_check):
        """测试进度回调"""
        mock_health_check.side_effect = [False, False, True]
        
        progress_calls = []
        def on_progress(elapsed, timeout):
            progress_calls.append((elapsed, timeout))
        
        result = wait_for_server(timeout=5, interval=0.1, on_progress=on_progress, check_log=False)
        assert result == True
        assert len(progress_calls) >= 2


class TestCheckServerReady:
    """测试检查服务器状态"""
    
    @patch('scripts.health_check.health_check', return_value=True)
    @patch('scripts.port_utils.check_port', return_value=True)
    def test_check_server_ready(self, mock_check_port, mock_health_check):
        """测试检查服务器状态"""
        result = check_server_ready()
        assert isinstance(result, dict)
        assert "port" in result
        assert "port_occupied" in result
        assert "health_ok" in result
        assert "ready" in result
        assert "status" in result
    
    @patch('scripts.health_check.health_check', return_value=True)
    @patch('scripts.port_utils.check_port', return_value=True)
    def test_check_server_ready_status(self, mock_check_port, mock_health_check):
        """测试服务器就绪状态"""
        result = check_server_ready()
        assert result["status"] == "ready"
        assert result["ready"] == True
    
    @patch('scripts.health_check.health_check', return_value=False)
    @patch('scripts.port_utils.check_port', return_value=True)
    def test_check_server_starting(self, mock_check_port, mock_health_check):
        """测试服务器启动中状态"""
        result = check_server_ready()
        assert result["status"] == "starting"
        assert result["ready"] == False
    
    @patch('scripts.health_check.health_check', return_value=False)
    @patch('scripts.port_utils.check_port', return_value=False)
    def test_check_server_not_started(self, mock_check_port, mock_health_check):
        """测试服务器未启动状态"""
        result = check_server_ready()
        assert result["status"] == "not_started"
        assert result["ready"] == False


class TestGetServerLogs:
    """测试获取服务器日志"""
    
    def test_get_server_logs_no_file(self):
        """测试没有日志文件"""
        with patch('os.path.exists', return_value=False):
            result = get_server_logs()
            assert result == []
    
    def test_get_server_logs_with_file(self, tmp_path):
        """测试有日志文件"""
        log_file = tmp_path / "server.log"
        log_file.write_text("line1\nline2\nline3\n")
        
        with patch('scripts.health_check.LOG_FILE', log_file):
            result = get_server_logs(lines=2)
            assert len(result) == 2
            assert "line2" in result[0]
            assert "line3" in result[1]
    
    def test_get_server_logs_read_error(self):
        """测试读取日志文件错误"""
        with patch('os.path.exists', return_value=True), \
             patch('builtins.open', side_effect=Exception("Read error")):
            result = get_server_logs()
            assert result == []


class TestClearServerLogs:
    """测试清除服务器日志"""
    
    def test_clear_server_logs_success(self, tmp_path):
        """测试成功清除日志"""
        log_file = tmp_path / "server.log"
        log_file.write_text("test log")
        
        with patch('scripts.health_check.LOG_FILE', log_file):
            result = clear_server_logs()
            assert result == True
            assert not log_file.exists()
    
    def test_clear_server_logs_no_file(self):
        """测试没有日志文件"""
        with patch('os.path.exists', return_value=False):
            result = clear_server_logs()
            assert result == True
    
    def test_clear_server_logs_error(self):
        """测试清除日志错误"""
        with patch('os.path.exists', return_value=True), \
             patch('os.remove', side_effect=Exception("Remove error")):
            result = clear_server_logs()
            assert result == False


class TestCheckDependencies:
    """测试检查依赖项"""
    
    def test_check_dependencies_returns_dict(self):
        """测试返回字典"""
        result = check_dependencies()
        assert isinstance(result, dict)
    
    def test_check_dependencies_keys(self):
        """测试字典键"""
        result = check_dependencies()
        assert "fastapi" in result
        assert "uvicorn" in result
        assert "sentence_transformers" in result
    
    def test_check_dependencies_values(self):
        """测试字典值类型"""
        result = check_dependencies()
        for key, value in result.items():
            assert isinstance(value, bool)


class TestCheckAllServices:
    """测试检查所有服务"""
    
    @patch('scripts.health_check.check_dependencies')
    @patch('scripts.port_utils.check_port')
    @patch('scripts.health_check.health_check')
    def test_check_all_services(self, mock_health_check, mock_check_port, mock_check_deps):
        """测试检查所有服务"""
        mock_health_check.return_value = True
        mock_check_port.return_value = True
        mock_check_deps.return_value = {"fastapi": True, "uvicorn": True, "sentence_transformers": True}
        
        result = check_all_services()
        assert isinstance(result, dict)
        assert "backend" in result
        assert "frontend" in result
        assert "dependencies" in result


class TestWaitForServerWithProgress:
    """测试带进度条等待服务器"""
    
    @patch('scripts.health_check.health_check', return_value=True)
    def test_wait_for_server_with_progress_success(self, mock_health_check):
        """测试带进度条等待成功"""
        result = wait_for_server_with_progress(timeout=5)
        assert result == True
    
    @patch('scripts.health_check.health_check', return_value=False)
    def test_wait_for_server_with_progress_timeout(self, mock_health_check):
        """测试带进度条等待超时"""
        result = wait_for_server_with_progress(timeout=1)
        assert result == False


class TestEdgeCases:
    """测试边界情况"""
    
    def test_health_check_zero_timeout(self):
        """测试零超时"""
        result = health_check(timeout=0)
        assert isinstance(result, bool)
    
    def test_wait_for_server_zero_timeout(self):
        """测试零超时等待"""
        with patch('scripts.health_check.health_check', return_value=False):
            result = wait_for_server(timeout=0, check_log=False)
            assert result == False
    
    def test_check_server_ready_custom_port(self):
        """测试自定义端口检查"""
        with patch('scripts.health_check.health_check', return_value=False), \
             patch('scripts.port_utils.check_port', return_value=False):
            result = check_server_ready(port=8080)
            assert result["port"] == 8080


class TestConcurrency:
    """测试并发情况"""
    
    @patch('scripts.health_check.health_check', return_value=True)
    def test_concurrent_health_check(self, mock_health_check):
        """测试并发健康检查"""
        results = []
        
        def check():
            results.append(health_check())
        
        threads = [threading.Thread(target=check) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        
        assert len(results) == 10
        for result in results:
            assert isinstance(result, bool)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])