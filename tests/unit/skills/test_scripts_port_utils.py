"""
Neurova 端口工具模块测试
测试 port_utils.py 中的端口检查、释放、进程查找等功能
"""

import sys
import socket
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

# 导入被测模块
from scripts.port_utils import (
    check_port, get_process_by_port, get_processes_by_port,
    kill_process, kill_port, wait_for_port, wait_for_port_free,
    find_free_port, get_port_info, print_port_info, cleanup_ports,
    get_network_info, print_network_info
)


class TestCheckPort:
    """测试端口检查"""
    
    def test_check_port_returns_bool(self):
        """测试 check_port 返回布尔值"""
        result = check_port(9527)
        assert isinstance(result, bool)
    
    def test_check_port_with_server(self):
        """测试检查正在使用的端口"""
        # 创建一个简单的服务器来占用端口
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('localhost', 0))
        port = server.getsockname()[1]
        server.listen(1)
        
        try:
            assert check_port(port) == True
        finally:
            server.close()
    
    def test_check_port_free_port(self):
        """测试检查空闲端口"""
        # 找一个空闲端口
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('localhost', 0))
        port = server.getsockname()[1]
        server.close()
        
        # 等待端口释放
        time.sleep(0.1)
        
        assert check_port(port) == False


class TestGetProcessByPort:
    """测试获取进程 ID"""
    
    def test_get_process_by_port_returns_none_for_free_port(self):
        """测试空闲端口返回 None"""
        # 找一个空闲端口
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('localhost', 0))
        port = server.getsockname()[1]
        server.close()
        
        # 等待端口释放
        time.sleep(0.1)
        
        result = get_process_by_port(port)
        assert result is None
    
    def test_get_process_by_port_with_server(self):
        """测试获取占用端口的进程 ID"""
        # 创建一个服务器来占用端口
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('localhost', 0))
        port = server.getsockname()[1]
        server.listen(1)
        
        try:
            result = get_process_by_port(port)
            # 在测试环境中，可能无法获取进程 ID
            # 但函数应该不会抛出异常
            assert result is None or isinstance(result, int)
        finally:
            server.close()


class TestGetProcessesByPort:
    """测试获取进程 ID 列表"""
    
    def test_get_processes_by_port_returns_list(self):
        """测试返回列表"""
        result = get_processes_by_port(9527)
        assert isinstance(result, list)
    
    def test_get_processes_by_port_free_port(self):
        """测试空闲端口返回空列表"""
        # 找一个空闲端口
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('localhost', 0))
        port = server.getsockname()[1]
        server.close()
        
        # 等待端口释放
        time.sleep(0.1)
        
        result = get_processes_by_port(port)
        assert result == []


class TestKillProcess:
    """测试终止进程"""
    
    def test_kill_process_invalid_pid(self):
        """测试终止无效 PID"""
        result = kill_process(999999)
        # 在测试环境中，可能返回 False 或 True
        # 但函数应该不会抛出异常
        assert isinstance(result, bool)


class TestWaitForPort:
    """测试等待端口"""
    
    def test_wait_for_port_with_server(self):
        """测试等待端口被占用"""
        # 创建一个服务器来占用端口
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('localhost', 0))
        port = server.getsockname()[1]
        server.listen(1)
        
        try:
            # 端口应该已经被占用
            result = wait_for_port(port, timeout=1)
            assert result == True
        finally:
            server.close()
    
    def test_wait_for_port_timeout(self):
        """测试等待端口超时"""
        # 找一个空闲端口
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('localhost', 0))
        port = server.getsockname()[1]
        server.close()
        
        # 等待端口释放
        time.sleep(0.1)
        
        # 等待端口被占用（应该超时）
        result = wait_for_port(port, timeout=1)
        assert result == False


class TestWaitForPortFree:
    """测试等待端口释放"""
    
    def test_wait_for_port_free_with_server(self):
        """测试等待端口释放"""
        # 创建一个服务器来占用端口
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('localhost', 0))
        port = server.getsockname()[1]
        server.listen(1)
        
        # 在另一个线程中关闭服务器
        def close_server():
            time.sleep(0.5)
            server.close()
        
        thread = threading.Thread(target=close_server)
        thread.start()
        
        try:
            # 等待端口释放
            result = wait_for_port_free(port, timeout=2)
            assert result == True
        finally:
            thread.join()


class TestFindFreePort:
    """测试查找空闲端口"""
    
    def test_find_free_port(self):
        """测试查找空闲端口"""
        port = find_free_port(9000, 9010)
        assert port is not None
        assert 9000 <= port <= 9010
        
        # 验证端口确实是空闲的
        assert check_port(port) == False
    
    def test_find_free_port_no_available(self):
        """测试没有可用端口"""
        # 模拟所有端口都被占用
        with patch('scripts.port_utils.check_port', return_value=True):
            port = find_free_port(9000, 9010)
            assert port is None


class TestGetPortInfo:
    """测试获取端口信息"""
    
    def test_get_port_info_returns_dict(self):
        """测试返回字典"""
        info = get_port_info(9527)
        assert isinstance(info, dict)
    
    def test_get_port_info_keys(self):
        """测试字典键"""
        info = get_port_info(9527)
        assert "port" in info
        assert "occupied" in info
        assert "pids" in info
        assert "process_count" in info
    
    def test_get_port_info_types(self):
        """测试字典值类型"""
        info = get_port_info(9527)
        assert isinstance(info["port"], int)
        assert isinstance(info["occupied"], bool)
        assert isinstance(info["pids"], list)
        assert isinstance(info["process_count"], int)


class TestGetNetworkInfo:
    """测试获取网络信息"""
    
    def test_get_network_info_returns_dict(self):
        """测试返回字典"""
        info = get_network_info()
        assert isinstance(info, dict)
    
    def test_get_network_info_keys(self):
        """测试字典键"""
        info = get_network_info()
        assert "hostname" in info
        assert "local_ip" in info
        assert "platform" in info
    
    def test_get_network_info_types(self):
        """测试字典值类型"""
        info = get_network_info()
        assert isinstance(info["hostname"], str)
        assert isinstance(info["local_ip"], str)
        assert isinstance(info["platform"], str)


class TestCleanupPorts:
    """测试清理端口"""
    
    def test_cleanup_ports_empty_list(self):
        """测试清理空列表"""
        result = cleanup_ports([])
        assert result == True
    
    def test_cleanup_ports_free_ports(self):
        """测试清理空闲端口"""
        # 找一些空闲端口
        ports = []
        for _ in range(3):
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(('localhost', 0))
            ports.append(server.getsockname()[1])
            server.close()
        
        # 等待端口释放
        time.sleep(0.1)
        
        result = cleanup_ports(ports)
        assert result == True


class TestEdgeCases:
    """测试边界情况"""
    
    def test_check_port_invalid_port(self):
        """测试无效端口"""
        # 端口 0 应该是无效的
        result = check_port(0)
        assert isinstance(result, bool)
    
    def test_check_port_high_port(self):
        """测试高端口"""
        # 端口 65535 是最大有效端口
        result = check_port(65535)
        assert isinstance(result, bool)
    
    def test_get_process_by_port_invalid_port(self):
        """测试无效端口获取进程"""
        result = get_process_by_port(0)
        assert result is None
    
    def test_wait_for_port_zero_timeout(self):
        """测试零超时"""
        result = wait_for_port(9527, timeout=0)
        assert isinstance(result, bool)


class TestConcurrency:
    """测试并发情况"""
    
    def test_concurrent_check_port(self):
        """测试并发端口检查"""
        results = []
        
        def check():
            results.append(check_port(9527))
        
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