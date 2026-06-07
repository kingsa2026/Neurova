#!/usr/bin/env python3
"""
Neurova 一键启动脚本 (Python 版，避免 CMD 引号/编码问题)
功能：启动后端服务器 → 等待就绪 → 启动 CLI 聊天 → 退出时清理
"""
import subprocess
import sys
import os
import time
import signal
import urllib.request
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable
PORT = 9527
HEALTH_URL = f"http://localhost:{PORT}/health"
LOG_FILE = os.path.join(SCRIPT_DIR, "server.log")

BANNER = """
╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║   ███╗   ██╗███████╗██╗   ██╗██████╗  ██████╗ ██╗   ██╗  █████╗   ║
║   ████╗  ██║██╔════╝██║   ██║██╔══██╗██╔═══██╗██║   ██║ ██╔══██╗  ║
║   ██╔██╗ ██║█████╗  ██║   ██║██████╔╝██║   ██║██║   ██║ ███████║  ║
║   ██║╚██╗██║██╔══╝  ██║   ██║██╔══██╗██║   ██║╚██╗ ██╔╝ ██╔══██║  ║
║   ██║ ╚████║███████╗╚██████╔╝██║  ██║╚██████╔╝ ╚████╔╝  ██║  ██║  ║
║   ╚═╝  ╚═══╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝   ╚═══╝   ╚═╝  ╚═╝  ║
║                                                                   ║
║                 智能无限，协作无间                                ║
╚═══════════════════════════════════════════════════════════════════╝
"""


def check_port(port):
    """检查端口是否被占用，返回占用的 PID 列表"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"],
            capture_output=True, text=True, timeout=10
        )
        pids = [int(p.strip()) for p in result.stdout.strip().split('\n') if p.strip().isdigit()]
        return pids
    except Exception:
        return []


def kill_pids(pids):
    """终止指定 PID 的进程"""
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
    time.sleep(1)


def kill_port(port):
    """释放指定端口"""
    pids = check_port(port)
    if pids:
        print(f"  [!] 端口 {port} 被进程 {pids} 占用，正在释放...")
        kill_pids(pids)
        # 强制终止残留
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
        time.sleep(1)
        remaining = check_port(port)
        if remaining:
            print(f"  [ERROR] 无法释放端口 {port}，进程 {remaining} 仍在运行")
            return False
        print(f"  [OK] 端口 {port} 已释放")
    else:
        print(f"  [OK] 端口 {port} 可用")
    return True


def health_check():
    """检查服务器健康状态"""
    try:
        req = urllib.request.Request(HEALTH_URL)
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def wait_for_server(timeout=60, interval=2):
    """等待服务器就绪"""
    start = time.time()
    attempt = 0
    while time.time() - start < timeout:
        attempt += 1
        # 检查服务器进程是否还在运行（通过日志中的致命错误）
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                if 'Server failed to start' in content:
                    print(f"\n  [ERROR] 服务器启动失败！日志内容：")
                    print("  " + "-" * 50)
                    for line in content.strip().split('\n')[-20:]:
                        print(f"  {line}")
                    print("  " + "-" * 50)
                    return False

        if health_check():
            return True

        elapsed = int(time.time() - start)
        print(f"  等待中... ({elapsed}s/{timeout}s)", end='\r')
        time.sleep(interval)

    print(f"\n  [ERROR] 服务器启动超时 ({timeout}秒)")
    if os.path.exists(LOG_FILE):
        print(f"  服务器日志 ({LOG_FILE})：")
        print("  " + "-" * 50)
        with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f.readlines()[-20:]:
                print(f"  {line}")
        print("  " + "-" * 50)
    else:
        print(f"  未生成日志文件，请手动运行: {PYTHON} start_server.py")
    return False


def main():
    os.chdir(SCRIPT_DIR)
    print(BANNER)

    # 检查虚拟环境
    venv_python = os.path.join(SCRIPT_DIR, ".venv", "Scripts", "python.exe")
    if not os.path.exists(venv_python):
        print("  [!] 虚拟环境不存在，正在运行安装...")
        subprocess.run([sys.executable, "install.py"])
        if not os.path.exists(venv_python):
            print("  [ERROR] 安装失败")
            input("按回车键退出...")
            return 1

    # 步骤 1：释放端口
    print("  [1/3] 检查端口...")
    if not kill_port(PORT):
        input("按回车键退出...")
        return 1

    # 步骤 2：启动后端服务器
    print("  [2/3] 启动后端服务器...")
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)

    # 启动服务器子进程，日志写入文件
    log_fh = open(LOG_FILE, 'w', encoding='utf-8')
    server_proc = subprocess.Popen(
        [PYTHON, "start_server.py"],
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        cwd=SCRIPT_DIR,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
    )

    # 等待服务器就绪
    if not wait_for_server(timeout=60):
        print("  服务器未能启动，正在清理...")
        server_proc.terminate()
        log_fh.close()
        input("按回车键退出...")
        return 1

    print("  [OK] 服务器已就绪！")

    # 步骤 3：启动 CLI 聊天
    print("  [3/3] 启动聊天客户端...\n")
    print("  " + "=" * 60)
    print("  提示: 输入消息开始聊天，输入 /help 查看命令，Ctrl+C 退出")
    print("  " + "=" * 60)
    print()

    try:
        cli_proc = subprocess.run([PYTHON, "cli.py"], cwd=SCRIPT_DIR)
    except KeyboardInterrupt:
        pass
    finally:
        # CLI 退出后清理
        print("\n  正在停止后端服务器...")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
        log_fh.close()
        # 确保端口释放
        kill_port(PORT)
        print("  已停止。再见！")

    return 0


if __name__ == "__main__":
    sys.exit(main())
