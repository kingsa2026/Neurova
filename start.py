#!/usr/bin/env python3
"""
Neurova 统一启动脚本
====================

启动前后端服务：
- 后端: FastAPI (端口 9527)
- 前端: Vite Dev Server (端口 8100)
- CLI:  命令行聊天客户端

环境要求:
- Python >= 3.12
- 虚拟环境 (.venv) 已创建

启动时自动检查环境，如不满足则自动执行一键安装（已安装的跳过）。
支持 Windows / Linux / macOS 跨平台运行。

使用方式:
    python start.py              # 同时启动前后端 (默认，自动检查环境)
    python start.py --backend    # 仅启动后端
    python start.py --frontend   # 仅启动前端
    python start.py --prod       # 生产模式（仅后端，服务静态文件）
    python start.py --cli        # 启动后端 + CLI 聊天
    python start.py --chat       # 启动前后端 + 自动打开浏览器
    python start.py --check      # 仅检查服务状态
    python start.py --skip-install  # 跳过自动环境检查

一键启动:
    Windows:  start.bat [--options]
    Linux/Mac: ./start.sh [--options]
"""

import argparse
import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from scripts.common import print_logo, c, Colors, ProgressBar
from scripts.config import (
    ROOT_DIR, FRONTEND_DIR, BACKEND_PORT, FRONTEND_PORT,
    get_venv_python, get_backend_script, is_venv_available,
    is_frontend_available,
)
from scripts.port_utils import check_port, kill_port, wait_for_port
from scripts.health_check import (
    health_check, wait_for_server, check_all_services, print_services_status,
)


# ═══════════════════════════════════════════════════════════════
# 服务启动
# ═══════════════════════════════════════════════════════════════

def _get_backend_python() -> list:
    """获取后端 Python 命令"""
    venv_python = get_venv_python()
    if venv_python.exists():
        return [str(venv_python)]
    return [sys.executable]


def start_backend(port: int = BACKEND_PORT, log_file: str = None) -> subprocess.Popen:
    """
    启动后端服务器
    
    Args:
        port: 后端端口
        log_file: 日志文件路径，None 表示不重定向
        
    Returns:
        subprocess.Popen: 服务器进程
    """
    print(f"\n  {c('▸', Colors.CYAN)} {c('启动后端服务', Colors.BOLD)}")
    print(f"    地址: {c(f'http://localhost:{port}', Colors.SKY_BLUE_BRIGHT)}")
    print(f"    API 文档: {c(f'http://localhost:{port}/docs', Colors.SKY_BLUE_BRIGHT)}")
    print(f"    健康检查: {c(f'http://localhost:{port}/health', Colors.SKY_BLUE_BRIGHT)}")
    print()

    env = os.environ.copy()
    env["NEUROVA_PORT"] = str(port)

    stdout_target = None
    stderr_target = None
    if log_file:
        log_dir = ROOT_DIR / "logs"
        log_dir.mkdir(exist_ok=True)
        stdout_target = open(log_dir / log_file, "w", encoding="utf-8")
        stderr_target = subprocess.STDOUT

    cmd = _get_backend_python() + [str(get_backend_script())]
    
    kwargs = {
        "cwd": str(ROOT_DIR),
        "env": env,
    }
    
    if stdout_target:
        kwargs["stdout"] = stdout_target
        kwargs["stderr"] = stderr_target
    
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    return subprocess.Popen(cmd, **kwargs), stdout_target


def start_frontend(port: int = FRONTEND_PORT, open_browser: bool = False) -> subprocess.Popen:
    """
    启动前端开发服务器
    
    Args:
        port: 前端端口
        open_browser: 是否在服务就绪后自动打开浏览器
        
    Returns:
        subprocess.Popen: 前端进程
    """
    print(f"\n  {c('▸', Colors.CYAN)} {c('启动前端服务', Colors.BOLD)}")
    print(f"    地址: {c(f'http://localhost:{port}', Colors.SKY_BLUE_BRIGHT)}")
    print(f"    API 代理: {c(f'http://localhost:{BACKEND_PORT}', Colors.SKY_BLUE_BRIGHT)}")
    print()

    if not is_frontend_available():
        print(f"  {c('✗', Colors.RED)} 前端目录不存在或缺少 package.json: {FRONTEND_DIR}")
        return None

    cmd = ["npm", "run", "dev", "--", "--port", str(port)]
    
    kwargs = {
        "cwd": str(FRONTEND_DIR),
        "shell": True,
    }
    
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    proc = subprocess.Popen(cmd, **kwargs)
    
    # 自动打开浏览器
    if open_browser:
        _open_chat_browser(port)
    
    return proc


def _open_chat_browser(port: int = FRONTEND_PORT):
    """等待前端就绪后自动打开浏览器"""
    url = f"http://localhost:{port}"
    print(f"  {c('▸', Colors.CYAN)} 等待前端就绪...")
    
    # 等待前端服务启动（最多 30 秒）
    for i in range(30):
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('localhost', port))
            sock.close()
            if result == 0:
                print(f"  {c('✓', Colors.GREEN)} 前端已就绪，正在打开浏览器...")
                webbrowser.open(url)
                return
        except Exception:
            pass
        time.sleep(1)
    
    print(f"  {c('!', Colors.YELLOW)} 前端启动超时，请手动打开: {url}")


def start_prod() -> tuple:
    """
    生产模式：后端服务静态文件
    
    Returns:
        tuple: (process, log_file_handle)
    """
    print(f"\n  {c('▸', Colors.CYAN)} {c('启动 Neurova (生产模式)', Colors.BOLD)}")
    print(f"    地址: {c(f'http://localhost:{BACKEND_PORT}', Colors.SKY_BLUE_BRIGHT)}")
    print(f"    API 文档: {c(f'http://localhost:{BACKEND_PORT}/docs', Colors.SKY_BLUE_BRIGHT)}")
    print()

    # 复制前端构建产物到后端静态目录
    static_dir = ROOT_DIR / "neurova" / "static"
    dist_dir = FRONTEND_DIR / "dist"

    if dist_dir.exists():
        import shutil
        if static_dir.exists():
            shutil.rmtree(static_dir)
        shutil.copytree(dist_dir, static_dir)
        print(f"  {c('✓', Colors.GREEN)} 前端文件已复制到 {static_dir}")

    return start_backend(BACKEND_PORT, log_file="server.log")


# ═══════════════════════════════════════════════════════════════
# 依赖检查
# ═══════════════════════════════════════════════════════════════

def check_python_deps() -> bool:
    """检查 Python 依赖"""
    try:
        import fastapi
        import uvicorn
        return True
    except ImportError:
        print(f"\n  {c('!', Colors.YELLOW)} 缺少 Python 依赖，正在安装...")
        venv_python = get_venv_python()
        if venv_python.exists():
            subprocess.run(
                [str(venv_python), "-m", "pip", "install", "-r", "requirements.txt"],
                cwd=str(ROOT_DIR), check=True,
            )
        else:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
                cwd=str(ROOT_DIR), check=True,
            )
        return True


def check_node_deps() -> bool:
    """检查 Node.js 依赖"""
    node_modules = FRONTEND_DIR / "node_modules"
    if not node_modules.exists():
        print(f"\n  {c('!', Colors.YELLOW)} 缺少前端依赖，正在安装...")
        subprocess.run(
            ["npm", "install"],
            cwd=str(FRONTEND_DIR), check=True, shell=True,
        )
    return True


# ═══════════════════════════════════════════════════════════════
# CLI 聊天
# ═══════════════════════════════════════════════════════════════

def start_cli() -> int:
    """启动 CLI 聊天客户端"""
    cli_script = ROOT_DIR / "cli.py"
    if not cli_script.exists():
        print(f"  {c('✗', Colors.RED)} CLI 脚本不存在: {cli_script}")
        return 1

    print(f"\n  {'=' * 60}")
    print(f"  提示: 输入消息开始聊天，输入 /help 查看命令，Ctrl+C 退出")
    print(f"  {'=' * 60}\n")

    python_cmd = _get_backend_python()
    try:
        result = subprocess.run(python_cmd + [str(cli_script)], cwd=str(ROOT_DIR))
        return result.returncode
    except KeyboardInterrupt:
        return 0


# ═══════════════════════════════════════════════════════════════
# 状态检查
# ═══════════════════════════════════════════════════════════════

def print_status():
    """打印服务状态"""
    print()
    print_services_status()
    print()


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def check_environment() -> bool:
    """
    检查运行环境是否满足要求
    
    检查项:
    1. Python 版本 >= 3.12
    2. 虚拟环境存在且可用
    3. pip 可用
    
    Returns:
        bool: 环境是否满足要求
    """
    from scripts.config import MIN_PYTHON_VERSION, is_venv_available, get_venv_python
    
    print(f"\n  {c('▸', Colors.CYAN)} {c('检查运行环境', Colors.BOLD)}")
    
    ok = True
    
    # 1. 检查 Python 版本
    current_version = sys.version_info[:2]
    required_version = MIN_PYTHON_VERSION
    
    if current_version < required_version:
        print(f"  {c('✗', Colors.RED)} Python 版本不符合要求")
        print(f"    当前版本: {c(f'{current_version[0]}.{current_version[1]}', Colors.YELLOW)}")
        print(f"    要求版本: {c(f'{required_version[0]}.{required_version[1]}+', Colors.GREEN)}")
        print(f"\n  {c('!', Colors.YELLOW)} 请升级 Python 到 {required_version[0]}.{required_version[1]} 或更高版本")
        ok = False
    else:
        print(f"  {c('✓', Colors.GREEN)} Python 版本: {current_version[0]}.{current_version[1]}")
    
    # 2. 检查虚拟环境
    if not is_venv_available():
        print(f"  {c('✗', Colors.RED)} 虚拟环境不存在或不完整")
        ok = False
    else:
        print(f"  {c('✓', Colors.GREEN)} 虚拟环境: 已就绪")
    
    # 3. 检查 pip 可用（仅在 venv 存在时检查）
    if ok:
        venv_python = get_venv_python()
        if venv_python.exists():
            try:
                result = subprocess.run(
                    [str(venv_python), "-m", "pip", "--version"],
                    capture_output=True, timeout=10,
                )
                if result.returncode == 0:
                    print(f"  {c('✓', Colors.GREEN)} pip: 可用")
                else:
                    print(f"  {c('!', Colors.YELLOW)} pip: 不可用（可选）")
            except Exception:
                print(f"  {c('!', Colors.YELLOW)} pip: 检查失败（可选）")
    
    return ok


def auto_install() -> bool:
    """
    自动执行一键安装
    
    Returns:
        bool: 安装是否成功
    """
    print(f"\n  {c('▸', Colors.CYAN)} {c('环境不满足要求，正在执行一键安装...', Colors.BOLD)}")
    
    install_script = ROOT_DIR / "install.py"
    if not install_script.exists():
        print(f"  {c('✗', Colors.RED)} 安装脚本不存在: {install_script}")
        return False
    
    try:
        # 使用当前 Python 解释器运行安装脚本
        result = subprocess.run(
            [sys.executable, str(install_script), "--lang", "zh"],
            cwd=str(ROOT_DIR),
            check=False,
        )
        
        if result.returncode == 0:
            print(f"\n  {c('✓', Colors.GREEN)} 一键安装完成")
            return True
        else:
            print(f"\n  {c('✗', Colors.RED)} 一键安装失败 (退出码: {result.returncode})")
            return False
            
    except KeyboardInterrupt:
        print(f"\n  {c('!', Colors.YELLOW)} 安装已取消")
        return False
    except Exception as e:
        print(f"\n  {c('✗', Colors.RED)} 安装过程出错: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Neurova 启动脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python start.py              # 同时启动前后端
  python start.py --backend    # 仅启动后端
  python start.py --frontend   # 仅启动前端
  python start.py --prod       # 生产模式
  python start.py --cli        # 启动后端 + CLI 聊天
  python start.py --chat       # 启动前后端 + 自动打开浏览器
  python start.py --check      # 检查服务状态
        """,
    )
    parser.add_argument("--backend", action="store_true", help="仅启动后端")
    parser.add_argument("--frontend", action="store_true", help="仅启动前端")
    parser.add_argument("--prod", action="store_true", help="生产模式（仅后端，服务静态文件）")
    parser.add_argument("--cli", action="store_true", help="启动后端 + CLI 聊天")
    parser.add_argument("--chat", action="store_true", help="启动前后端 + 自动打开浏览器聊天")
    parser.add_argument("--check", action="store_true", help="检查服务状态并退出")
    parser.add_argument("--backend-port", type=int, default=BACKEND_PORT, help="后端端口")
    parser.add_argument("--frontend-port", type=int, default=FRONTEND_PORT, help="前端端口")
    parser.add_argument("--skip-install", action="store_true", help="跳过自动安装检查")
    args = parser.parse_args()

    print_logo(subtitle="智能无限，协作无间")

    # 环境检查（除非 --check 模式或 --skip-install）
    if not args.check and not args.skip_install:
        if not check_environment():
            print(f"\n  {c('!', Colors.YELLOW)} 正在尝试自动修复环境问题...")
            if not auto_install():
                print(f"\n  {c('✗', Colors.RED)} 无法自动修复环境，请手动运行: python install.py")
                return 1
            # 安装完成后重新检查
            print(f"\n  {c('▸', Colors.CYAN)} 重新检查环境...")
            if not check_environment():
                print(f"\n  {c('✗', Colors.RED)} 环境检查仍然失败，请手动运行: python install.py")
                return 1

    # 仅检查状态
    if args.check:
        print_status()
        return 0

    processes = []  # [(name, process, log_handle)]

    try:
        # 生产模式
        if args.prod:
            check_python_deps()
            proc, log_fh = start_prod()
            processes.append(("Backend (Production)", proc, log_fh))

        # 仅后端
        elif args.backend and not args.frontend:
            check_python_deps()
            if check_port(args.backend_port):
                print(f"  {c('✓', Colors.GREEN)} 后端已在运行 (端口 {args.backend_port})")
            else:
                proc, log_fh = start_backend(args.backend_port)
                processes.append(("Backend", proc, log_fh))
                if not wait_for_server(port=args.backend_port):
                    print(f"\n  {c('✗', Colors.RED)} 后端启动失败")
                    return 1

        # 仅前端
        elif args.frontend and not args.backend:
            check_node_deps()
            if check_port(args.frontend_port):
                print(f"  {c('✓', Colors.GREEN)} 前端已在运行 (端口 {args.frontend_port})")
            else:
                proc = start_frontend(args.frontend_port)
                if proc:
                    processes.append(("Frontend", proc, None))

        # CLI 模式
        elif args.cli:
            check_python_deps()
            if not check_port(args.backend_port):
                proc, log_fh = start_backend(args.backend_port)
                processes.append(("Backend", proc, log_fh))
                if not wait_for_server(port=args.backend_port):
                    print(f"\n  {c('✗', Colors.RED)} 后端启动失败")
                    return 1
            else:
                print(f"  {c('✓', Colors.GREEN)} 后端已在运行 (端口 {args.backend_port})")
            
            return start_cli()

        # Chat 模式：前后端 + 自动打开浏览器
        elif args.chat:
            check_python_deps()
            
            # 启动后端
            if check_port(args.backend_port):
                print(f"  {c('✓', Colors.GREEN)} 后端已在运行 (端口 {args.backend_port})")
            else:
                proc, log_fh = start_backend(args.backend_port, log_file="server.log")
                processes.append(("Backend", proc, log_fh))
            
            # 等待后端就绪
            if not wait_for_server(port=args.backend_port):
                print(f"\n  {c('✗', Colors.RED)} 后端启动失败")
                return 1

            # 启动前端并自动打开浏览器
            if check_port(args.frontend_port):
                print(f"  {c('✓', Colors.GREEN)} 前端已在运行 (端口 {args.frontend_port})")
                _open_chat_browser(args.frontend_port)
            else:
                check_node_deps()
                proc = start_frontend(args.frontend_port, open_browser=True)
                if proc:
                    processes.append(("Frontend", proc, None))

        # 默认：同时启动前后端
        else:
            check_python_deps()
            
            # 启动后端
            if check_port(args.backend_port):
                print(f"  {c('✓', Colors.GREEN)} 后端已在运行 (端口 {args.backend_port})")
            else:
                proc, log_fh = start_backend(args.backend_port, log_file="server.log")
                processes.append(("Backend", proc, log_fh))
            
            # 等待后端就绪
            if not wait_for_server(port=args.backend_port):
                print(f"\n  {c('✗', Colors.RED)} 后端启动失败")
                return 1

            # 启动前端
            if check_port(args.frontend_port):
                print(f"  {c('✓', Colors.GREEN)} 前端已在运行 (端口 {args.frontend_port})")
            else:
                check_node_deps()
                proc = start_frontend(args.frontend_port, open_browser=True)
                if proc:
                    processes.append(("Frontend", proc, None))

        if not processes:
            print(f"\n  {c('✓', Colors.GREEN)} 所有服务已在运行")
            print_status()
            return 0

        print(f"\n  {c('✓', Colors.GREEN)} 所有服务已启动")
        print(f"\n  按 {c('Ctrl+C', Colors.YELLOW)} 停止所有服务\n")

        # 等待进程结束
        while True:
            for name, proc, log_fh in processes:
                if proc.poll() is not None:
                    print(f"\n  {c('!', Colors.YELLOW)} {name} 已停止 (退出码: {proc.returncode})")
                    raise KeyboardInterrupt
            time.sleep(1)

    except KeyboardInterrupt:
        print(f"\n\n  正在停止所有服务...")
        for name, proc, log_fh in processes:
            try:
                proc.terminate()
                proc.wait(timeout=5)
                print(f"  {c('✓', Colors.GREEN)} {name} 已停止")
            except subprocess.TimeoutExpired:
                proc.kill()
                print(f"  {c('!', Colors.YELLOW)} {name} 已强制停止")
            except Exception:
                pass
            finally:
                if log_fh:
                    try:
                        log_fh.close()
                    except Exception:
                        pass

        # 确保端口释放
        for name, proc, _ in processes:
            if "Backend" in name:
                kill_port(args.backend_port)
            elif "Frontend" in name:
                kill_port(args.frontend_port)

        print(f"\n  所有服务已停止。再见！")

    return 0


if __name__ == "__main__":
    sys.exit(main())
