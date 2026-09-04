#!/usr/bin/env python3
"""
启动 Neurova API 服务器
"""

import sys
import os
import logging

# 强制 UTF-8 输出：stdout/stderr 重定向到文件时 Python 默认用系统 ANSI
# 代码页（中文 Windows = GBK），桌面壳按 UTF-8 读取会乱码。须在 stderr
# 首次使用前设置（io 编码在解释器初始化后只认环境变量/重配置）。
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:
    pass

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

def _get_app_version():
    try:
        from neurova import __version__

        return __version__
    except Exception:
        return "unknown"


def main():
    """启动服务器"""
    print("=" * 60)
    print("Starting Neurova API Server...")
    print("=" * 60)

    try:
        from neurova.api.app import create_app
        import uvicorn

        # torch 环境预检：c10.dll 初始化失败（缺 VC++ 运行库）→ 自动下载安装。
        # 任何失败只告警，不阻断启动。
        try:
            from neurova.core.env_check import preflight_torch_runtime

            preflight_torch_runtime()
        except Exception as _env_err:  # noqa: BLE001 - 预检失败不阻断启动
            print(f"Warning: torch 环境预检失败（忽略）: {_env_err}")

        # 进化权重持久化装配（显式；单例本身零 IO 副作用）
        try:
            from neurova.evolution.closed_loop import bootstrap_evolution_persistence

            bootstrap_evolution_persistence()
        except Exception as _persist_err:  # noqa: BLE001 - 权重恢复失败不阻断启动
            print(f"Warning: 进化权重恢复失败（忽略）: {_persist_err}")

        # 创建应用
        app = create_app()

        print(f"App: {app.title}")
        print(f"Version: {app.version}")
        print(f"Docs: http://localhost:9527/docs")
        print(f"Health: http://localhost:9527/health")
        print("=" * 60)

        # 启动服务器
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=9527,
            log_level="info",
        )

    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except Exception as e:
        print(f"Server failed to start: {e}")
        import traceback
        traceback.print_exc()

        # 启动失败上报远程错误日志（尽力而为：无网/关闭/失败都不影响退出）
        try:
            from neurova.core.crash_report import report_startup_failure

            report_startup_failure(e, stage="startup", app_version=_get_app_version())
        except Exception:
            pass
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
