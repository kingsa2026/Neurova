"""
Neurova 健康检查模块
提供统一的健康检查、服务器等待、日志监控等功能
"""

import time
import urllib.request
import urllib.error
import os
from typing import Optional, Callable

from .config import get_health_url, HEALTH_CHECK_TIMEOUT, HEALTH_CHECK_INTERVAL, LOG_FILE


def health_check(port: Optional[int] = None, timeout: int = 3) -> bool:
    """
    检查服务器健康状态
    
    Args:
        port: 端口号，默认使用配置的后端端口
        timeout: 请求超时时间（秒）
        
    Returns:
        bool: 服务器是否健康
    """
    url = get_health_url(port)
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def wait_for_server(
    port: Optional[int] = None,
    timeout: int = HEALTH_CHECK_TIMEOUT,
    interval: int = HEALTH_CHECK_INTERVAL,
    on_progress: Optional[Callable[[int, int], None]] = None,
    check_log: bool = True,
) -> bool:
    """
    等待服务器就绪
    
    检查顺序: 健康检查（权威信号）优先，日志检查仅作辅助。
    如果健康检查通过则立即返回 True，不会被陈旧日志误导。
    
    Args:
        port: 端口号，默认使用配置的后端端口
        timeout: 超时时间（秒）
        interval: 检查间隔（秒）
        on_progress: 进度回调函数 (elapsed, timeout)
        check_log: 是否检查日志文件中的错误
        
    Returns:
        bool: 服务器是否在超时前就绪
    """
    start = time.time()
    attempt = 0
    log_mtime = _get_log_mtime()
    
    while time.time() - start < timeout:
        attempt += 1
        elapsed = int(time.time() - start)
        
        # 健康检查（权威信号）—— 优先于日志检查
        if health_check(port):
            return True
        
        # 日志检查（辅助信号）—— 仅在健康检查失败时检查
        # 仅检查本次启动后写入的日志（忽略陈旧日志）
        if check_log and os.path.exists(LOG_FILE):
            try:
                current_mtime = os.path.getmtime(LOG_FILE)
                # log_mtime is None 表示日志文件在启动前不存在（新建），此时任何内容都值得检查
                log_is_new = log_mtime is None
                log_was_updated = log_mtime is not None and current_mtime > log_mtime
                if log_is_new or log_was_updated:
                    with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        # 仅检测真正的启动失败，忽略网络重试等非致命错误
                        # 致命标志: "Server failed to start", Python Traceback, "启动失败"
                        # 非致命(忽略): HuggingFace/网络重试 (WinError, Retry, huggingface_hub)
                        fatal_markers = [
                            'Server failed to start',
                            'Traceback (most recent call last)',
                            '启动失败',
                        ]
                        has_fatal = any(marker in content for marker in fatal_markers)
                        if has_fatal:
                            lines = content.strip().split('\n')
                            fatal_lines = [l for l in lines if any(m in l for m in fatal_markers)]
                            if fatal_lines:
                                print(f"\n  [ERROR] 服务器启动失败！")
                                print("  " + "-" * 50)
                                for line in lines[-20:]:
                                    print(f"  {line}")
                                print("  " + "-" * 50)
                                return False
            except Exception:
                pass
        
        # 进度回调
        if on_progress:
            on_progress(elapsed, timeout)
        else:
            print(f"  等待中... ({elapsed}s/{timeout}s)", end='\r')
        
        time.sleep(interval)
    
    # 超时处理
    print(f"\n  [ERROR] 服务器启动超时 ({timeout}秒)")
    if os.path.exists(LOG_FILE):
        print(f"  服务器日志 ({LOG_FILE})：")
        print("  " + "-" * 50)
        try:
            with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f.readlines()[-20:]:
                    print(f"  {line}")
        except Exception:
            print("  [无法读取日志文件]")
        print("  " + "-" * 50)
    else:
        print(f"  未生成日志文件，请手动运行: python start_server.py")
    
    return False


def _get_log_mtime() -> Optional[float]:
    """
    获取日志文件的修改时间（调用时刻的快照）
    
    Returns:
        Optional[float]: 日志文件修改时间戳，不存在则返回 None
    """
    try:
        if os.path.exists(LOG_FILE):
            return os.path.getmtime(LOG_FILE)
    except Exception:
        pass
    return None


def check_server_ready(port: Optional[int] = None) -> dict:
    """
    检查服务器状态
    
    Args:
        port: 端口号，默认使用配置的后端端口
        
    Returns:
        dict: 服务器状态信息
    """
    from .port_utils import check_port
    
    health_ok = health_check(port)
    port_occupied = check_port(port or 9527)
    
    return {
        "port": port or 9527,
        "port_occupied": port_occupied,
        "health_ok": health_ok,
        "ready": health_ok,
        "status": "ready" if health_ok else ("starting" if port_occupied else "not_started"),
    }


def print_server_status(port: Optional[int] = None) -> None:
    """
    打印服务器状态
    
    Args:
        port: 端口号，默认使用配置的后端端口
    """
    from .common import c, Colors
    
    status = check_server_ready(port)
    
    if status["ready"]:
        print(f"  服务器状态: {c('就绪', Colors.GREEN)}")
    elif status["port_occupied"]:
        print(f"  服务器状态: {c('启动中', Colors.YELLOW)}")
    else:
        print(f"  服务器状态: {c('未启动', Colors.RED)}")
    
    print(f"  端口 {status['port']}: {'占用' if status['port_occupied'] else '可用'}")
    print(f"  健康检查: {'通过' if status['health_ok'] else '失败'}")


def monitor_server_health(
    port: Optional[int] = None,
    interval: int = 30,
    callback: Optional[Callable[[bool], None]] = None,
) -> None:
    """
    监控服务器健康状态
    
    Args:
        port: 端口号，默认使用配置的后端端口
        interval: 检查间隔（秒）
        callback: 状态变化回调函数
    """
    last_status = None
    
    while True:
        current_status = health_check(port)
        
        if last_status is not None and current_status != last_status:
            if callback:
                callback(current_status)
            else:
                status_str = "健康" if current_status else "不健康"
                print(f"  [监控] 服务器状态变化: {status_str}")
        
        last_status = current_status
        time.sleep(interval)


def get_server_logs(lines: int = 50) -> list:
    """
    获取服务器日志
    
    Args:
        lines: 获取最后几行
        
    Returns:
        list: 日志行列表
    """
    if not os.path.exists(LOG_FILE):
        return []
    
    try:
        with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()
            return all_lines[-lines:] if len(all_lines) > lines else all_lines
    except Exception:
        return []


def print_server_logs(lines: int = 20) -> None:
    """
    打印服务器日志
    
    Args:
        lines: 打印最后几行
    """
    from .common import c, Colors
    
    logs = get_server_logs(lines)
    
    if not logs:
        print(f"  {c('无日志文件', Colors.YELLOW)}")
        return
    
    print(f"  {c('服务器日志', Colors.SKY_BLUE_BRIGHT)} (最后 {len(logs)} 行):")
    print("  " + "-" * 50)
    for line in logs:
        print(f"  {line.rstrip()}")
    print("  " + "-" * 50)


def clear_server_logs() -> bool:
    """
    清除服务器日志
    
    Returns:
        bool: 是否成功清除
    """
    try:
        if os.path.exists(LOG_FILE):
            os.remove(LOG_FILE)
        return True
    except Exception:
        return False


def wait_for_server_with_progress(
    port: Optional[int] = None,
    timeout: int = HEALTH_CHECK_TIMEOUT,
    description: str = "等待服务器就绪",
) -> bool:
    """
    带进度条等待服务器就绪
    
    Args:
        port: 端口号
        timeout: 超时时间
        description: 进度条描述
        
    Returns:
        bool: 服务器是否就绪
    """
    from .common import ProgressBar
    
    pb = ProgressBar(description, total=timeout, unit="s", show_eta=True)
    pb.start()
    
    start = time.time()
    while time.time() - start < timeout:
        elapsed = time.time() - start
        pb.update(elapsed)
        
        if health_check(port):
            pb.update(timeout)
            pb.finish(success=True, message="服务器就绪")
            return True
        
        time.sleep(HEALTH_CHECK_INTERVAL)
    
    pb.finish(success=False, message="超时")
    return False


def check_dependencies() -> dict:
    """
    检查依赖项
    
    Returns:
        dict: 依赖项状态
    """
    dependencies = {
        "fastapi": False,
        "uvicorn": False,
        "sentence_transformers": False,
        # Computer Use（桌面控制 + 浏览器自动化）
        "PIL": False,          # Pillow：桌面截图
        "pyautogui": False,    # 鼠标/键盘控制
        "playwright": False,   # 浏览器自动化
    }
    
    for dep in dependencies:
        try:
            __import__(dep)
            dependencies[dep] = True
        except ImportError:
            pass
    
    return dependencies


def print_dependencies_status() -> None:
    """打印依赖项状态"""
    from .common import c, Colors
    
    deps = check_dependencies()
    
    print(c("依赖项状态:", Colors.SKY_BLUE_BRIGHT))
    for dep, available in deps.items():
        status = c("✓", Colors.GREEN) if available else c("✗", Colors.RED)
        print(f"  {status} {dep}")


def check_all_services() -> dict:
    """
    检查所有服务状态
    
    Returns:
        dict: 服务状态
    """
    from .port_utils import check_port
    from .config import BACKEND_PORT, FRONTEND_PORT
    
    return {
        "backend": {
            "port": BACKEND_PORT,
            "occupied": check_port(BACKEND_PORT),
            "healthy": health_check(BACKEND_PORT),
        },
        "frontend": {
            "port": FRONTEND_PORT,
            "occupied": check_port(FRONTEND_PORT),
        },
        "dependencies": check_dependencies(),
    }


def print_services_status() -> None:
    """打印所有服务状态"""
    from .common import c, Colors
    
    services = check_all_services()
    
    print(c("服务状态:", Colors.SKY_BLUE_BRIGHT))
    
    # 后端状态
    backend = services["backend"]
    if backend["healthy"]:
        status = c("健康", Colors.GREEN)
    elif backend["occupied"]:
        status = c("启动中", Colors.YELLOW)
    else:
        status = c("未启动", Colors.RED)
    print(f"  后端 (端口 {backend['port']}): {status}")
    
    # 前端状态
    frontend = services["frontend"]
    if frontend["occupied"]:
        status = c("运行中", Colors.GREEN)
    else:
        status = c("未启动", Colors.RED)
    print(f"  前端 (端口 {frontend['port']}): {status}")
    
    # 依赖项状态
    deps = services["dependencies"]
    available = sum(1 for v in deps.values() if v)
    total = len(deps)
    print(f"  依赖项: {available}/{total} 可用")