#!/usr/bin/env python3
"""
Neurova 统一启动脚本
===================

启动前后端服务：
- 后端: FastAPI (端口 9527)
- 前端: Vite Dev Server (端口 8100)

使用方式:
    python start.py              # 同时启动前后端
    python start.py --backend    # 仅启动后端
    python start.py --frontend   # 仅启动前端
    python start.py --prod       # 生产模式（仅后端，服务静态文件）
"""

import argparse
import os
import subprocess
import sys
import time
import signal
from pathlib import Path

# 项目根目录
ROOT_DIR = Path(__file__).parent.resolve()
FRONTEND_DIR = ROOT_DIR / "neuUI"
BACKEND_PORT = 9527
FRONTEND_PORT = 8100


def check_python_deps():
    """检查 Python 依赖"""
    try:
        import fastapi
        import uvicorn
        return True
    except ImportError:
        print("[!] 缺少 Python 依赖，正在安装...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
            cwd=ROOT_DIR,
            check=True,
        )
        return True


def check_node_deps():
    """检查 Node.js 依赖"""
    node_modules = FRONTEND_DIR / "node_modules"
    if not node_modules.exists():
        print("[!] 缺少前端依赖，正在安装...")
        subprocess.run(
            ["npm", "install"],
            cwd=FRONTEND_DIR,
            check=True,
            shell=True,
        )
    return True


def start_backend(port: int = BACKEND_PORT):
    """启动后端服务器"""
    print(f"\n{'='*60}")
    print(f"  启动 Neurova 后端服务")
    print(f"  地址: http://localhost:{port}")
    print(f"  API 文档: http://localhost:{port}/docs")
    print(f"  健康检查: http://localhost:{port}/health")
    print(f"{'='*60}\n")

    env = os.environ.copy()
    env["NEUROVA_PORT"] = str(port)

    return subprocess.Popen(
        [sys.executable, "start_server.py"],
        cwd=ROOT_DIR,
        env=env,
    )


def start_frontend(port: int = FRONTEND_PORT):
    """启动前端开发服务器"""
    print(f"\n{'='*60}")
    print(f"  启动 Neurova 前端服务")
    print(f"  地址: http://localhost:{port}")
    print(f"  API 代理: http://localhost:{BACKEND_PORT}")
    print(f"{'='*60}\n")

    return subprocess.Popen(
        ["npm", "run", "dev", "--", "--port", str(port)],
        cwd=FRONTEND_DIR,
        shell=True,
    )


def start_prod():
    """生产模式：后端服务静态文件"""
    print(f"\n{'='*60}")
    print(f"  启动 Neurova (生产模式)")
    print(f"  地址: http://localhost:{BACKEND_PORT}")
    print(f"  API 文档: http://localhost:{BACKEND_PORT}/docs")
    print(f"{'='*60}\n")

    # 复制前端构建产物到后端静态目录
    static_dir = ROOT_DIR / "neurova" / "static"
    dist_dir = FRONTEND_DIR / "dist"

    if dist_dir.exists():
        import shutil
        if static_dir.exists():
            shutil.rmtree(static_dir)
        shutil.copytree(dist_dir, static_dir)
        print(f"[OK] 前端文件已复制到 {static_dir}")

    return subprocess.Popen(
        [sys.executable, "start_server.py"],
        cwd=ROOT_DIR,
    )


def main():
    parser = argparse.ArgumentParser(description="Neurova 启动脚本")
    parser.add_argument("--backend", action="store_true", help="仅启动后端")
    parser.add_argument("--frontend", action="store_true", help="仅启动前端")
    parser.add_argument("--prod", action="store_true", help="生产模式")
    parser.add_argument("--backend-port", type=int, default=BACKEND_PORT, help="后端端口")
    parser.add_argument("--frontend-port", type=int, default=FRONTEND_PORT, help="前端端口")
    args = parser.parse_args()

    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   ███╗   ██╗███████╗██╗   ██╗██████╗  ██████╗ ██╗   ██╗  ║
    ║   ████╗  ██║██╔════╝██║   ██║██╔══██╗██╔═══██╗██║   ██║  ║
    ║   ██╔██╗ ██║█████╗  ██║   ██║██████╔╝██║   ██║██║   ██║  ║
    ║   ██║╚██╗██║██╔══╝  ██║   ██║██╔══██╗██║   ██║╚██╗ ██╔╝  ║
    ║   ██║ ╚████║███████╗╚██████╔╝██║  ██║╚██████╔╝ ╚████╔╝   ║
    ║   ╚═╝  ╚═══╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝   ╚═══╝    ║
    ║                                                           ║
    ║            智能无限，协作无间                                ║
    ╚═══════════════════════════════════════════════════════════╝
    """)

    processes = []

    try:
        if args.prod:
            # 生产模式
            check_python_deps()
            proc = start_prod()
            processes.append(("Backend (Production)", proc))

        elif args.backend and not args.frontend:
            # 仅后端
            check_python_deps()
            proc = start_backend(args.backend_port)
            processes.append(("Backend", proc))

        elif args.frontend and not args.backend:
            # 仅前端
            check_node_deps()
            proc = start_frontend(args.frontend_port)
            processes.append(("Frontend", proc))

        else:
            # 同时启动前后端
            check_python_deps()
            check_node_deps()

            backend_proc = start_backend(args.backend_port)
            processes.append(("Backend", backend_proc))

            # 等待后端启动
            time.sleep(2)

            frontend_proc = start_frontend(args.frontend_port)
            processes.append(("Frontend", frontend_proc))

        print("\n[OK] 所有服务已启动")
        print("\n按 Ctrl+C 停止所有服务\n")

        # 等待进程结束
        while True:
            for name, proc in processes:
                if proc.poll() is not None:
                    print(f"\n[!] {name} 已停止 (退出码: {proc.returncode})")
                    raise KeyboardInterrupt
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n正在停止所有服务...")
        for name, proc in processes:
            try:
                proc.terminate()
                proc.wait(timeout=5)
                print(f"[OK] {name} 已停止")
            except Exception:
                proc.kill()
                print(f"[!] {name} 已强制停止")

        print("\n所有服务已停止。再见！")


if __name__ == "__main__":
    main()
