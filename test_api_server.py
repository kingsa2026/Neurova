#!/usr/bin/env python3
"""
测试 API 服务器是否能正常启动
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """测试核心模块导入"""
    print("Testing imports...")

    modules = [
        "neurova.core.event_bus",
        "neurova.core.log_level",
        "neurova.core.module_system",
        "neurova.core.health_checker",
        "neurova.core.startup_manager",
        "neurova.interfaces.api_standard",
        "neurova.api.auth",
        "neurova.api.middleware",
        "neurova.api.endpoints",
        "neurova.api.endpoints.health",
        "neurova.api.endpoints.chat",
        "neurova.api.endpoints.agent",
        "neurova.api.endpoints.auth",
        "neurova.api.endpoints.memory",
        "neurova.api.endpoints.model",
        "neurova.api.endpoints.provider",
        "neurova.api.endpoints.settings",
        "neurova.api.endpoints.stats",
        "neurova.api.endpoints.logs",
        "neurova.api.endpoints.generation",
        "neurova.api.endpoints.monitor",
        "neurova.api.app",
    ]

    failed = []
    for mod in modules:
        try:
            __import__(mod)
            print(f"  OK: {mod}")
        except Exception as e:
            print(f"  FAIL: {mod} - {e}")
            failed.append(mod)

    if failed:
        print(f"\n{len(failed)} modules failed to import")
        return False

    print(f"\nAll {len(modules)} modules imported successfully")
    return True


def test_create_app():
    """测试创建 FastAPI 应用"""
    print("\nTesting app creation...")

    try:
        from neurova.api.app import create_app, get_app_state

        app = create_app()
        print(f"  App created: {app.title}")

        state = get_app_state()
        print(f"  App state created: {state is not None}")

        # 检查路由
        routes = [route.path for route in app.routes]
        print(f"  Routes registered: {len(routes)}")

        # 检查关键路由
        key_routes = ["/health", "/test", "/docs"]
        for route in key_routes:
            if route in routes:
                print(f"    - {route}: OK")
            else:
                print(f"    - {route}: MISSING")

        return True

    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_health_checker():
    """测试健康检查器"""
    print("\nTesting health checker...")

    try:
        from neurova.core.health_checker import get_health_checker, HealthChecker

        checker = get_health_checker()
        print(f"  Health checker created: {checker is not None}")

        # 运行检查
        results = checker.run_all_checks()
        print(f"  Checks run: {len(results)}")

        for name, result in results.items():
            print(f"    - {name}: {result.status.value}")

        report = checker.get_report()
        print(f"  Overall status: {report['status']}")

        return True

    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_event_bus():
    """测试事件总线"""
    print("\nTesting event bus...")

    try:
        from neurova.core.event_bus import get_event_bus, EventPriority

        bus = get_event_bus()
        print(f"  Event bus created: {bus is not None}")
        print(f"  Event bus running: {bus.is_running()}")

        # 测试订阅和发布
        received_events = []

        def test_handler(event):
            received_events.append(event)

        bus.subscribe("test.event", test_handler, priority=EventPriority.NORMAL)
        bus.publish("test.event", data={"test": True})

        print(f"  Events received: {len(received_events)}")

        # 清理
        bus.unsubscribe("test.event", test_handler)

        return True

    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_startup_manager():
    """测试启动管理器"""
    print("\nTesting startup manager...")

    try:
        from neurova.core.startup_manager import get_startup_manager

        manager = get_startup_manager()
        print(f"  Startup manager created: {manager is not None}")

        status = manager.get_status()
        print(f"  Status: {status}")

        return True

    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_auth_module():
    """测试认证模块"""
    print("\nTesting auth module...")

    try:
        from neurova.api.auth import (
            create_access_token,
            create_refresh_token,
            verify_access_token,
            verify_refresh_token,
            hash_password,
            verify_password,
        )

        # 测试 token 创建和验证
        test_data = {"sub": "test_user", "username": "test"}
        access_token = create_access_token(test_data)
        refresh_token = create_refresh_token(test_data)

        print(f"  Access token created: {len(access_token) > 0}")
        print(f"  Refresh token created: {len(refresh_token) > 0}")

        # 验证 token
        payload = verify_access_token(access_token)
        print(f"  Access token verified: {payload is not None}")
        print(f"    - sub: {payload.get('sub') if payload else 'N/A'}")

        payload = verify_refresh_token(refresh_token)
        print(f"  Refresh token verified: {payload is not None}")

        # 测试密码哈希
        password = "test_password"
        hashed = hash_password(password)
        print(f"  Password hashed: {len(hashed) > 0}")

        verified = verify_password(password, hashed)
        print(f"  Password verified: {verified}")

        return True

    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主测试函数"""
    print("=" * 60)
    print("Neurova API Server Test")
    print("=" * 60)

    results = []

    # 运行测试
    results.append(("Imports", test_imports()))
    results.append(("Event Bus", test_event_bus()))
    results.append(("Health Checker", test_health_checker()))
    results.append(("Startup Manager", test_startup_manager()))
    results.append(("Auth Module", test_auth_module()))
    results.append(("App Creation", test_create_app()))

    # 打印结果
    print("\n" + "=" * 60)
    print("Test Results")
    print("=" * 60)

    passed = 0
    failed = 0
    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  {name}: {status}")
        if result:
            passed += 1
        else:
            failed += 1

    print(f"\nTotal: {passed + failed}, Passed: {passed}, Failed: {failed}")

    if failed > 0:
        print("\nSome tests failed!")
        return 1
    else:
        print("\nAll tests passed!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
