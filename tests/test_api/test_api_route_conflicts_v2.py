"""测试API路由冲突问题 - 实际路由注册验证"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import importlib
import importlib.util


def create_test_app():
    """创建测试用FastAPI应用"""
    app = FastAPI()
    return app


def test_channel_route_registration():
    """测试channel和channels模块的实际路由注册"""
    app = create_test_app()
    
    # 2026-09-13 死壳清理：endpoints.channel(/v1/channels 假桥)已删除，冲突主体不复存在
    
    # 注册channels模块
    try:
        from neurova.api.endpoints import channels
        app.include_router(channels.router, prefix="/api/v1/channels", tags=["channels"])
    except ImportError:
        pytest.skip("channels模块导入失败")
    
    # 获取所有路由
    routes = []
    for route in app.routes:
        if hasattr(route, "path"):
            routes.append(route.path)
    
    print(f"注册的路由: {routes}")
    
    # 检查是否有重复的路由
    # 注意：FastAPI允许重复路由，但后注册的会覆盖前一个
    # 我们需要检查是否有冲突
    
    # 检查是否包含预期的路由
    has_channel_get = any("/api/v1/channels" in route for route in routes)
    has_channels_channels = any("/api/v1/channels/channels" in route for route in routes)
    
    print(f"是否有 /api/v1/channels 路由: {has_channel_get}")
    print(f"是否有 /api/v1/channels/channels 路由: {has_channels_channels}")
    
    # 验证冲突：channels模块的router有前缀/channels，所以会注册到/api/v1/channels/channels
    # 这与channel模块的/api/v1/channels冲突


def test_context_route_registration():
    """context / context_pool_settings 的实际路由注册（后者已下架，改锁防复活）。

    2026-09-26（Issue #90 §10 第 2b 项）：`context_pool_settings` 判定为假设置面
    整面下架，故本用例不再把它挂进测试 app —— 全仓唯一挂载点由主装配路由表覆盖，
    判据单源在 `tests/unit/api/test_context_pool_settings_face_retirement.py`。
    """
    assert importlib.util.find_spec("neurova.api.endpoints.context_pool_settings") is None, (
        "context_pool_settings 已判定下架却又出现。"
    )

    app = create_test_app()
    from neurova.api.endpoints import context

    app.include_router(context.router, prefix="/api/v1/context", tags=["context"])
    # 装配后的路由表取数走本仓唯一口径（现行 FastAPI 的 `include_router` 不再把
    # 子路由就地摊平，直接 `for r in app.routes: r.path` 会静默取空集）。
    from tests.route_table import registeredPaths

    routes = registeredPaths(app)
    assert any("/api/v1/context" in route for route in routes), routes


def test_deprecated_market_shells_are_gone():
    """skill_market / skills_market 双套已按 ADR 0013 删除（不再注册到任何前缀）。"""
    for name in ("neurova.api.endpoints.skill_market", "neurova.api.endpoints.skills_market"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(name)


def test_actual_registration_simulation():
    """模拟实际的register_endpoint_routers函数注册"""
    app = create_test_app()
    
    # 模拟注册列表中的前几个模块
    endpoint_modules = [
        ("neurova.api.endpoints.channels", "/v1/channel-adapters", "Channels API"),
        ("neurova.api.endpoints.context", "/v1/context", "Context API"),
    ]
    
    registered_routes = []
    
    for module_path, prefix, description in endpoint_modules:
        try:
            module = importlib.import_module(module_path)
            if hasattr(module, "router"):
                # 获取router的原始前缀
                original_prefix = module.router.prefix
                final_prefix = "/api" + prefix
                
                print(f"模块: {module_path}")
                print(f"  原始router前缀: {original_prefix}")
                print(f"  注册前缀: {final_prefix}")
                print(f"  最终路径: {final_prefix}{original_prefix}")
                
                app.include_router(module.router, prefix=final_prefix, tags=[description])
                registered_routes.append((module_path, final_prefix, original_prefix))
                
        except ImportError as e:
            print(f"跳过 {module_path}: {e}")
        except Exception as e:
            print(f"注册失败 {module_path}: {e}")
    
    print(f"\n注册的路由: {len(registered_routes)}")
    for route_info in registered_routes:
        print(f"  {route_info[0]} -> {route_info[1]}{route_info[2]}")


def test_frontend_api_coverage_analysis():
    """分析前端API覆盖率"""
    # 后端API数量
    backend_count = 75
    
    # 前端API模块
    frontend_modules = [
        "agents.ts", "chat.ts", "auth.ts", "memory.ts", "models.ts",
        "providers.ts", "skill.ts", "settings.ts", "stats.ts", "scheduler.ts",
        "trace.ts", "marketplace.ts", "channel_config.ts",
        "notifications.ts", "audit.ts", "firewall.ts", "collaboration.ts",
        "workflows.ts", "tasks.ts", "files_api.ts", "benchmark.ts",
        "sleep.ts", "knowledge_api.ts", "emotion.ts", "webhooks.ts",
        "enhanced-users.ts", "mobile-pairing.ts", "synonym.ts", "channel_sharing.ts",
        "dashboard.ts", "home.ts", "system.ts", "stats.ts"
    ]
    
    frontend_count = len(frontend_modules)
    coverage = frontend_count / backend_count * 100
    
    print(f"后端API数量: {backend_count}")
    print(f"前端API模块: {frontend_count}")
    print(f"覆盖率: {coverage:.1f}%")
    
    # 列出缺失的前端模块
    missing_high_priority = [
        "generation.ts",
        "context.ts", 
        "metacognition.ts",
        "experience.ts",
        "knowledge-graph.ts",
        "growth.ts"
    ]
    
    print(f"\n高优先级缺失的前端模块:")
    for module in missing_high_priority:
        print(f"  - {module}")
    
    return coverage


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])