#!/usr/bin/env python3
"""
启动 Neurova API 服务器
"""

import sys
import os
import logging

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

def main():
    """启动服务器"""
    print("=" * 60)
    print("Starting Neurova API Server...")
    print("=" * 60)

    try:
        from neurova.api.app import create_app
        import uvicorn

        # 创建应用
        app = create_app()

        print(f"App: {app.title}")
        print(f"Version: {app.version}")
        print(f"Docs: http://localhost:8000/docs")
        print(f"Health: http://localhost:8000/health")
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
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
