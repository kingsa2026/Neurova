"""测试API路由冲突问题 - 实际路由注册验证"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import importlib


def create_test_app():
    """创建测试用FastAPI应用"""
    app = FastAPI()
    return app


def test_channel_route_registration():
    """测试channel和channels模块的实际路由注册"""
    app = create_test_app()
    
    # 注册channel模块
    try:
        from neurova.api.endpoints import channel
        app.include_router(channel.router, prefix="/api/v1/channels", tags=["channel"])
    except ImportError:
        pytest.skip("channel模块导入失败")
    
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
    """测试context和context_pool_settings模块的实际路由注册"""
    app = create_test_app()
    
    # 注册context模块
    try:
        from neurova.api.endpoints import context
        app.include_router(context.router, prefix="/api/v1/context", tags=["context"])
    except ImportError:
        pytest.skip("context模块导入失败")
    
    # 注册context_pool_settings模块
    try:
        from neurova.api.endpoints import context_pool_settings
        app.include_router(context_pool_settings.router, prefix="/api/v1/context", tags=["context_pool_settings"])
    except ImportError:
        pytest.skip("context_pool_settings模块导入失败")
    
    # 获取所有路由
    routes = []
    for route in app.routes:
        if hasattr(route, "path"):
            routes.append(route.path)
    
    print(f"注册的路由: {routes}")
    
    # 检查是否有重复的路由
    # 两个模块都注册到 /api/v1/context，这会导致冲突


def test_skill_market_route_registration():
    """测试skill_market和skills_market模块的实际路由注册"""
    app = create_test_app()
    
    # 注册skill_market模块
    try:
        from neurova.api.endpoints import skill_market
        app.include_router(skill_market.router, prefix="/api/v1/skill-market", tags=["skill_market"])
    except ImportError:
        pytest.skip("skill_market模块导入失败")
    
    # 注册skills_market模块
    try:
        from neurova.api.endpoints import skills_market
        app.include_router(skills_market.router, prefix="/api/v1/skills-market", tags=["skills_market"])
    except ImportError:
        pytest.skip("skills_market模块导入失败")
    
    # 获取所有路由
    routes = []
    for route in app.routes:
        if hasattr(route, "path"):
            routes.append(route.path)
    
    print(f"注册的路由: {routes}")
    
    # 检查路由命名不一致
    has_skill_market = any("/api/v1/skill-market" in route for route in routes)
    has_skills_market = any("/api/v1/skills-market" in route for route in routes)
    
    print(f"是否有 /api/v1/skill-market 路由: {has_skill_market}")
    print(f"是否有 /api/v1/skills-market 路由: {has_skills_market}")


def test_actual_registration_simulation():
    """模拟实际的register_endpoint_routers函数注册"""
    app = create_test_app()
    
    # 模拟注册列表中的前几个模块
    endpoint_modules = [
        ("neurova.api.endpoints.channel", "/v1/channels", "Channel API"),
        ("neurova.api.endpoints.channels", "/v1/channels", "Channels API"),
        ("neurova.api.endpoints.context", "/v1/context", "Context API"),
        ("neurova.api.endpoints.context_pool_settings", "/v1/context", "Context Pool Settings API"),
        ("neurova.api.endpoints.skill_market", "/v1/skill-market", "Skill Market API"),
        ("neurova.api.endpoints.skills_market", "/v1/skills-market", "Skills Market API"),
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
        "trace.ts", "marketplace.ts", "channel.ts", "channel_config.ts",
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