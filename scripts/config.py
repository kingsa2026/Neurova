"""
Neurova 配置管理模块
统一管理项目路径、端口、环境变量等配置
"""

import os
from pathlib import Path
from typing import Optional

# 项目根目录
ROOT_DIR = Path(__file__).parent.parent.resolve()

# 目录配置
VENV_DIR = ROOT_DIR / ".venv"
FRONTEND_DIR = ROOT_DIR / "neuUI"
MODELS_DIR = ROOT_DIR / "models"
LOGS_DIR = ROOT_DIR / "logs"

# Python 版本要求
MIN_PYTHON_VERSION = (3, 10)

# 端口配置
BACKEND_PORT = 9527
FRONTEND_PORT = 8100

# 健康检查配置
HEALTH_CHECK_TIMEOUT = 60  # 秒
HEALTH_CHECK_INTERVAL = 2  # 秒

# 日志配置
LOG_FILE = LOGS_DIR / "server.log"


def get_venv_python() -> Path:
    """
    获取虚拟环境的 Python 路径
    
    Returns:
        Path: 虚拟环境 Python 路径
    """
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    else:
        return VENV_DIR / "bin" / "python"


def get_venv_pip() -> Path:
    """
    获取虚拟环境的 pip 路径
    
    Returns:
        Path: 虚拟环境 pip 路径
    """
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "pip.exe"
    else:
        return VENV_DIR / "bin" / "pip"


def get_health_url(port: Optional[int] = None) -> str:
    """
    获取健康检查 URL
    
    Args:
        port: 端口号，默认使用配置的后端端口
        
    Returns:
        str: 健康检查 URL
    """
    port = port or BACKEND_PORT
    return f"http://localhost:{port}/health"


def get_api_url(port: Optional[int] = None) -> str:
    """
    获取 API URL
    
    Args:
        port: 端口号，默认使用配置的后端端口
        
    Returns:
        str: API URL
    """
    port = port or BACKEND_PORT
    return f"http://localhost:{port}"


def get_docs_url(port: Optional[int] = None) -> str:
    """
    获取 API 文档 URL
    
    Args:
        port: 端口号，默认使用配置的后端端口
        
    Returns:
        str: API 文档 URL
    """
    port = port or BACKEND_PORT
    return f"http://localhost:{port}/docs"


def ensure_directories() -> None:
    """确保必要的目录存在"""
    LOGS_DIR.mkdir(exist_ok=True)
    MODELS_DIR.mkdir(exist_ok=True)


def get_backend_script() -> Path:
    """
    获取后端启动脚本路径
    
    Returns:
        Path: 后端启动脚本路径
    """
    return ROOT_DIR / "start_server.py"


def get_frontend_package_json() -> Path:
    """
    获取前端 package.json 路径
    
    Returns:
        Path: package.json 路径
    """
    return FRONTEND_DIR / "package.json"


def is_frontend_available() -> bool:
    """
    检查前端目录是否可用
    
    Returns:
        bool: 前端目录是否存在且包含 package.json
    """
    return FRONTEND_DIR.exists() and get_frontend_package_json().exists()


def is_venv_available() -> bool:
    """
    检查虚拟环境是否可用
    
    Returns:
        bool: 虚拟环境是否存在
    """
    return VENV_DIR.exists() and get_venv_python().exists()


def get_environment_info() -> dict:
    """
    获取环境信息
    
    Returns:
        dict: 环境信息
    """
    import sys
    
    return {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": sys.platform,
        "root_dir": str(ROOT_DIR),
        "venv_dir": str(VENV_DIR),
        "frontend_dir": str(FRONTEND_DIR),
        "models_dir": str(MODELS_DIR),
        "logs_dir": str(LOGS_DIR),
        "backend_port": BACKEND_PORT,
        "frontend_port": FRONTEND_PORT,
        "venv_available": is_venv_available(),
        "frontend_available": is_frontend_available(),
    }


def print_environment_info() -> None:
    """打印环境信息"""
    from .common import c, Colors
    
    info = get_environment_info()
    
    print(c("环境信息:", Colors.SKY_BLUE_BRIGHT))
    print(f"  Python: {info['python_version']}")
    print(f"  平台: {info['platform']}")
    print(f"  项目目录: {info['root_dir']}")
    print(f"  虚拟环境: {'✓' if info['venv_available'] else '✗'}")
    print(f"  前端目录: {'✓' if info['frontend_available'] else '✗'}")
    print(f"  后端端口: {info['backend_port']}")
    print(f"  前端端口: {info['frontend_port']}")


# 导入 sys 以便在模块级别使用
import sys