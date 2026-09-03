"""
Neurova 配置管理模块测试
测试 config.py 中的配置管理功能
"""

import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

# 导入被测模块
from scripts.config import (
    ROOT_DIR, VENV_DIR, FRONTEND_DIR, MODELS_DIR, LOGS_DIR,
    MIN_PYTHON_VERSION, BACKEND_PORT, FRONTEND_PORT,
    HEALTH_CHECK_TIMEOUT, HEALTH_CHECK_INTERVAL, LOG_FILE,
    get_venv_python, get_venv_pip, get_health_url, get_api_url,
    get_docs_url, ensure_directories, get_backend_script,
    get_frontend_package_json, is_frontend_available, is_venv_available,
    get_environment_info, print_environment_info
)


class TestDirectoryConfig:
    """测试目录配置"""
    
    def test_root_dir_is_path(self):
        """测试 ROOT_DIR 是 Path 对象"""
        assert isinstance(ROOT_DIR, Path)
    
    def test_root_dir_exists(self):
        """测试 ROOT_DIR 存在"""
        assert ROOT_DIR.exists()
    
    def test_venv_dir_is_path(self):
        """测试 VENV_DIR 是 Path 对象"""
        assert isinstance(VENV_DIR, Path)
    
    def test_frontend_dir_is_path(self):
        """测试 FRONTEND_DIR 是 Path 对象"""
        assert isinstance(FRONTEND_DIR, Path)
    
    def test_models_dir_is_path(self):
        """测试 MODELS_DIR 是 Path 对象"""
        assert isinstance(MODELS_DIR, Path)
    
    def test_logs_dir_is_path(self):
        """测试 LOGS_DIR 是 Path 对象"""
        assert isinstance(LOGS_DIR, Path)
    
    def test_directory_relationships(self):
        """测试目录关系"""
        assert VENV_DIR.parent == ROOT_DIR
        assert FRONTEND_DIR.parent == ROOT_DIR
        assert MODELS_DIR.parent == ROOT_DIR
        assert LOGS_DIR.parent == ROOT_DIR


class TestPortConfig:
    """测试端口配置"""
    
    def test_backend_port_is_int(self):
        """测试后端端口是整数"""
        assert isinstance(BACKEND_PORT, int)
    
    def test_frontend_port_is_int(self):
        """测试前端端口是整数"""
        assert isinstance(FRONTEND_PORT, int)
    
    def test_ports_are_different(self):
        """测试前后端端口不同"""
        assert BACKEND_PORT != FRONTEND_PORT
    
    def test_ports_are_valid(self):
        """测试端口有效性"""
        assert 1024 <= BACKEND_PORT <= 65535
        assert 1024 <= FRONTEND_PORT <= 65535


class TestPythonVersion:
    """测试 Python 版本配置"""
    
    def test_min_python_version_is_tuple(self):
        """测试最小 Python 版本是元组"""
        assert isinstance(MIN_PYTHON_VERSION, tuple)
    
    def test_min_python_version_length(self):
        """测试最小 Python 版本长度"""
        assert len(MIN_PYTHON_VERSION) == 2
    
    def test_min_python_version_values(self):
        """测试最小 Python 版本值"""
        major, minor = MIN_PYTHON_VERSION
        assert major >= 3
        assert minor >= 0


class TestHealthCheckConfig:
    """测试健康检查配置"""
    
    def test_health_check_timeout_is_int(self):
        """测试健康检查超时是整数"""
        assert isinstance(HEALTH_CHECK_TIMEOUT, int)
    
    def test_health_check_interval_is_int(self):
        """测试健康检查间隔是整数"""
        assert isinstance(HEALTH_CHECK_INTERVAL, int)
    
    def test_health_check_timeout_positive(self):
        """测试健康检查超时为正数"""
        assert HEALTH_CHECK_TIMEOUT > 0
    
    def test_health_check_interval_positive(self):
        """测试健康检查间隔为正数"""
        assert HEALTH_CHECK_INTERVAL > 0
    
    def test_health_check_interval_less_than_timeout(self):
        """测试健康检查间隔小于超时"""
        assert HEALTH_CHECK_INTERVAL < HEALTH_CHECK_TIMEOUT


class TestLogFile:
    """测试日志文件配置"""
    
    def test_log_file_is_path(self):
        """测试 LOG_FILE 是 Path 对象"""
        assert isinstance(LOG_FILE, Path)
    
    def test_log_file_parent_is_root(self):
        """测试日志文件父目录是根目录"""
        assert LOG_FILE.parent == ROOT_DIR


class TestHelperFunctions:
    """测试辅助函数"""
    
    def test_get_venv_python(self):
        """测试获取虚拟环境 Python 路径"""
        python_path = get_venv_python()
        assert isinstance(python_path, Path)
        assert python_path.parent.parent == VENV_DIR
    
    def test_get_venv_pip(self):
        """测试获取虚拟环境 pip 路径"""
        pip_path = get_venv_pip()
        assert isinstance(pip_path, Path)
        assert pip_path.parent.parent == VENV_DIR
    
    def test_get_health_url_default(self):
        """测试获取默认健康检查 URL"""
        url = get_health_url()
        assert "localhost" in url
        assert str(BACKEND_PORT) in url
        assert "/health" in url
    
    def test_get_health_url_custom_port(self):
        """测试获取自定义端口健康检查 URL"""
        url = get_health_url(port=8080)
        assert "8080" in url
    
    def test_get_api_url_default(self):
        """测试获取默认 API URL"""
        url = get_api_url()
        assert "localhost" in url
        assert str(BACKEND_PORT) in url
    
    def test_get_api_url_custom_port(self):
        """测试获取自定义端口 API URL"""
        url = get_api_url(port=8080)
        assert "8080" in url
    
    def test_get_docs_url_default(self):
        """测试获取默认文档 URL"""
        url = get_docs_url()
        assert "localhost" in url
        assert str(BACKEND_PORT) in url
        assert "/docs" in url
    
    def test_get_docs_url_custom_port(self):
        """测试获取自定义端口文档 URL"""
        url = get_docs_url(port=8080)
        assert "8080" in url
    
    def test_get_backend_script(self):
        """测试获取后端脚本路径"""
        script = get_backend_script()
        assert isinstance(script, Path)
        assert script.name == "start_server.py"
        assert script.parent == ROOT_DIR
    
    def test_get_frontend_package_json(self):
        """测试获取前端 package.json 路径"""
        package_json = get_frontend_package_json()
        assert isinstance(package_json, Path)
        assert package_json.name == "package.json"
        assert package_json.parent == FRONTEND_DIR


class TestAvailabilityChecks:
    """测试可用性检查"""
    
    def test_is_frontend_available(self):
        """测试前端可用性检查"""
        result = is_frontend_available()
        assert isinstance(result, bool)
    
    def test_is_venv_available(self):
        """测试虚拟环境可用性检查"""
        result = is_venv_available()
        assert isinstance(result, bool)
    
    @patch('scripts.config.FRONTEND_DIR', Path('/nonexistent'))
    def test_is_frontend_available_nonexistent(self):
        """测试前端目录不存在时返回 False"""
        assert is_frontend_available() == False
    
    @patch('scripts.config.VENV_DIR', Path('/nonexistent'))
    def test_is_venv_available_nonexistent(self):
        """测试虚拟环境不存在时返回 False"""
        assert is_venv_available() == False


class TestEnsureDirectories:
    """测试目录创建"""
    
    def test_ensure_directories(self, tmp_path):
        """测试确保目录存在"""
        with patch('scripts.config.LOGS_DIR', tmp_path / 'logs'), \
             patch('scripts.config.MODELS_DIR', tmp_path / 'models'):
            ensure_directories()
            assert (tmp_path / 'logs').exists()
            assert (tmp_path / 'models').exists()


class TestEnvironmentInfo:
    """测试环境信息"""
    
    def test_get_environment_info(self):
        """测试获取环境信息"""
        info = get_environment_info()
        assert isinstance(info, dict)
        assert "python_version" in info
        assert "platform" in info
        assert "root_dir" in info
        assert "venv_dir" in info
        assert "frontend_dir" in info
        assert "models_dir" in info
        assert "logs_dir" in info
        assert "backend_port" in info
        assert "frontend_port" in info
        assert "venv_available" in info
        assert "frontend_available" in info
    
    def test_environment_info_types(self):
        """测试环境信息类型"""
        info = get_environment_info()
        assert isinstance(info["python_version"], str)
        assert isinstance(info["platform"], str)
        assert isinstance(info["root_dir"], str)
        assert isinstance(info["backend_port"], int)
        assert isinstance(info["frontend_port"], int)
        assert isinstance(info["venv_available"], bool)
        assert isinstance(info["frontend_available"], bool)


class TestEdgeCases:
    """测试边界情况"""
    
    def test_root_dir_is_absolute(self):
        """测试 ROOT_DIR 是绝对路径"""
        assert ROOT_DIR.is_absolute()
    
    def test_all_paths_are_absolute(self):
        """测试所有路径都是绝对路径"""
        assert VENV_DIR.is_absolute()
        assert FRONTEND_DIR.is_absolute()
        assert MODELS_DIR.is_absolute()
        assert LOGS_DIR.is_absolute()
        assert LOG_FILE.is_absolute()
    
    def test_ports_are_positive(self):
        """测试端口为正数"""
        assert BACKEND_PORT > 0
        assert FRONTEND_PORT > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])