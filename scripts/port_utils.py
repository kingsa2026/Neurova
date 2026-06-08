"""
Neurova 端口工具模块
提供跨平台的端口检查、释放、进程查找等功能
"""

import socket
import subprocess
import sys
import time
import signal
import os
from typing import List, Optional, Tuple


def check_port(port: int) -> bool:
    """
    检查端口是否被占用（跨平台）
    
    Args:
        port: 端口号
        
    Returns:
        bool: 端口是否被占用
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(('localhost', port))
            return result == 0
    except Exception:
        return False


def get_process_by_port(port: int) -> Optional[int]:
    """
    获取占用端口的进程 ID（跨平台）
    
    Args:
        port: 端口号
        
    Returns:
        Optional[int]: 进程 ID，如果没有找到则返回 None
    """
    try:
        if sys.platform == "win32":
            # Windows: 使用 netstat
            result = subprocess.run(
                ['netstat', '-ano'],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if f':{port}' in line and 'LISTENING' in line:
                        parts = line.split()
                        if parts and parts[-1].isdigit():
                            return int(parts[-1])
        else:
            # Unix/Linux/Mac: 使用 lsof
            result = subprocess.run(
                ['lsof', '-i', f':{port}', '-t'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                if pids and pids[0].isdigit():
                    return int(pids[0])
    except Exception:
        pass
    return None


def get_processes_by_port(port: int) -> List[int]:
    """
    获取占用端口的所有进程 ID（跨平台）
    
    Args:
        port: 端口号
        
    Returns:
        List[int]: 进程 ID 列表
    """
    pids = []
    try:
        if sys.platform == "win32":
            # Windows: 使用 netstat
            result = subprocess.run(
                ['netstat', '-ano'],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if f':{port}' in line and 'LISTENING' in line:
                        parts = line.split()
                        if parts and parts[-1].isdigit():
                            pid = int(parts[-1])
                            if pid not in pids:
                                pids.append(pid)
        else:
            # Unix/Linux/Mac: 使用 lsof
            result = subprocess.run(
                ['lsof', '-i', f':{port}', '-t'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                for pid_str in result.stdout.strip().split('\n'):
                    if pid_str.isdigit():
                        pid = int(pid_str)
                        if pid not in pids:
                            pids.append(pid)
    except Exception:
        pass
    return pids


def kill_process(pid: int) -> bool:
    """
    终止指定进程
    
    Args:
        pid: 进程 ID
        
    Returns:
        bool: 是否成功终止
    """
    try:
        if sys.platform == "win32":
            # Windows: 使用 taskkill
            result = subprocess.run(
                ['taskkill', '/PID', str(pid), '/F'],
                capture_output=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            return result.returncode == 0
        else:
            # Unix/Linux/Mac: 使用 kill
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.5)
            # 检查进程是否还在运行
            try:
                os.kill(pid, 0)  # 检查进程是否存在
                # 进程还在，强制终止
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # 进程已终止
            return True
    except Exception:
        return False


def kill_port(port: int) -> bool:
    """
    释放指定端口
    
    Args:
        port: 端口号
        
    Returns:
        bool: 是否成功释放
    """
    pids = get_processes_by_port(port)
    if not pids:
        return True  # 端口未被占用
    
    print(f"  [!] 端口 {port} 被进程 {pids} 占用，正在释放...")
    
    # 先尝试优雅终止
    for pid in pids:
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ['taskkill', '/PID', str(pid)],
                    capture_output=True,
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                )
            else:
                os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
    
    time.sleep(1)
    
    # 检查是否还有进程占用
    remaining = get_processes_by_port(port)
    if remaining:
        print(f"  [!] 强制终止残留进程 {remaining}...")
        for pid in remaining:
            kill_process(pid)
        time.sleep(1)
    
    # 最终检查
    if check_port(port):
        print(f"  [ERROR] 无法释放端口 {port}")
        return False
    
    print(f"  [OK] 端口 {port} 已释放")
    return True


def wait_for_port(port: int, timeout: int = 60, interval: int = 2) -> bool:
    """
    等待端口可用（被占用）
    
    Args:
        port: 端口号
        timeout: 超时时间（秒）
        interval: 检查间隔（秒）
        
    Returns:
        bool: 端口是否在超时前变为可用
    """
    start = time.time()
    while time.time() - start < timeout:
        if check_port(port):
            return True
        time.sleep(interval)
    return False


def wait_for_port_free(port: int, timeout: int = 30, interval: int = 1) -> bool:
    """
    等待端口释放（未被占用）
    
    Args:
        port: 端口号
        timeout: 超时时间（秒）
        interval: 检查间隔（秒）
        
    Returns:
        bool: 端口是否在超时前变为可用
    """
    start = time.time()
    while time.time() - start < timeout:
        if not check_port(port):
            return True
        time.sleep(interval)
    return False


def find_free_port(start_port: int = 9000, end_port: int = 9999) -> Optional[int]:
    """
    查找可用端口
    
    Args:
        start_port: 起始端口
        end_port: 结束端口
        
    Returns:
        Optional[int]: 可用端口号，如果没有找到则返回 None
    """
    for port in range(start_port, end_port + 1):
        if not check_port(port):
            return port
    return None


def get_port_info(port: int) -> dict:
    """
    获取端口信息
    
    Args:
        port: 端口号
        
    Returns:
        dict: 端口信息
    """
    is_occupied = check_port(port)
    pids = get_processes_by_port(port) if is_occupied else []
    
    return {
        "port": port,
        "occupied": is_occupied,
        "pids": pids,
        "process_count": len(pids),
    }


def print_port_info(port: int) -> None:
    """
    打印端口信息
    
    Args:
        port: 端口号
    """
    from .common import c, Colors
    
    info = get_port_info(port)
    
    if info["occupied"]:
        print(f"  端口 {port}: {c('占用', Colors.RED)} (进程: {info['pids']})")
    else:
        print(f"  端口 {port}: {c('可用', Colors.GREEN)}")


def cleanup_ports(ports: List[int]) -> bool:
    """
    清理多个端口
    
    Args:
        ports: 端口号列表
        
    Returns:
        bool: 是否所有端口都已清理
    """
    success = True
    for port in ports:
        if check_port(port):
            if not kill_port(port):
                success = False
    return success


def get_network_info() -> dict:
    """
    获取网络信息
    
    Returns:
        dict: 网络信息
    """
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        hostname = "unknown"
        local_ip = "127.0.0.1"
    
    return {
        "hostname": hostname,
        "local_ip": local_ip,
        "platform": sys.platform,
    }


def print_network_info() -> None:
    """打印网络信息"""
    from .common import c, Colors
    
    info = get_network_info()
    
    print(c("网络信息:", Colors.SKY_BLUE_BRIGHT))
    print(f"  主机名: {info['hostname']}")
    print(f"  本地 IP: {info['local_ip']}")
    print(f"  平台: {info['platform']}")