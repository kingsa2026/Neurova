#!/usr/bin/env python3
"""
测试路由注册
"""

import sys
sys.path.insert(0, '.')

from neurova.api.app import create_app

app = create_app()

# 打印所有路由
print("注册的路由:")
for route in app.routes:
    if hasattr(route, 'path'):
        print(f"  {route.path} - {route.methods if hasattr(route, 'methods') else 'N/A'}")

# 检查特定路由
print("\n检查上下文池设置路由:")
context_routes = [r for r in app.routes if hasattr(r, 'path') and 'pool-settings' in r.path]
for route in context_routes:
    print(f"  {route.path} - {route.methods if hasattr(route, 'methods') else 'N/A'}")