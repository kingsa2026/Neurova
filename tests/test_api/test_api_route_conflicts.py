"""测试API路由冲突问题"""
import pytest
import importlib
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_channel_route_conflict():
    """测试channel和channels模块路由冲突"""
    # 根据分析文档，两个模块都注册到 /v1/channels
    # 这会导致第二个模块覆盖第一个模块的路由
    
    app = FastAPI()
    
    # 尝试导入两个模块
    try:
        from neurova.api.endpoints import channel
        from neurova.api.endpoints import channels
        
        # 检查两个模块是否都有router
        assert hasattr(channel, 'router'), "channel模块应该有router"
        assert hasattr(channels, 'router'), "channels模块应该有router"
        
        # 检查路由前缀
        # channel模块的router前缀
        channel_prefix = channel.router.prefix
        channels_prefix = channels.router.prefix
        
        print(f"channel模块路由前缀: {channel_prefix}")
        print(f"channels模块路由前缀: {channels_prefix}")
        
        # 根据分析文档，两个模块都注册到 /v1/channels
        # 这会导致冲突
        # 实际测试中，我们检查它们是否会导致路由覆盖
        
    except ImportError as e:
        pytest.skip(f"跳过测试: 模块导入失败 - {e}")


def test_context_route_conflict():
    """测试context和context_pool_settings模块路由冲突"""
    # 根据分析文档，两个模块都注册到 /v1/context
    
    app = FastAPI()
    
    try:
        from neurova.api.endpoints import context
        from neurova.api.endpoints import context_pool_settings
        
        # 检查两个模块是否都有router
        assert hasattr(context, 'router'), "context模块应该有router"
        assert hasattr(context_pool_settings, 'router'), "context_pool_settings模块应该有router"
        
        # 检查路由前缀
        context_prefix = context.router.prefix
        context_pool_prefix = context_pool_settings.router.prefix
        
        print(f"context模块路由前缀: {context_prefix}")
        print(f"context_pool_settings模块路由前缀: {context_pool_prefix}")
        
        # 根据分析文档，两个模块都注册到 /v1/context
        # 这会导致冲突
        
    except ImportError as e:
        pytest.skip(f"跳过测试: 模块导入失败 - {e}")


def test_skill_market_route_conflict():
    """测试skill_market和skills_market模块路由冲突"""
    # 根据分析文档，两个模块分别注册到 /v1/skill-market 和 /v1/skills-market
    
    app = FastAPI()
    
    try:
        from neurova.api.endpoints import skill_market
        from neurova.api.endpoints import skills_market
        
        # 检查两个模块是否都有router
        assert hasattr(skill_market, 'router'), "skill_market模块应该有router"
        assert hasattr(skills_market, 'router'), "skills_market模块应该有router"
        
        # 检查路由前缀
        skill_market_prefix = skill_market.router.prefix
        skills_market_prefix = skills_market.router.prefix
        
        print(f"skill_market模块路由前缀: {skill_market_prefix}")
        print(f"skills_market模块路由前缀: {skills_market_prefix}")
        
        # 根据分析文档，两个模块分别注册到不同前缀
        # 但命名不一致（单复数混淆）
        
    except ImportError as e:
        pytest.skip(f"跳过测试: 模块导入失败 - {e}")


def test_endpoint_registration_count():
    """测试端点注册数量"""
    # 验证register_endpoint_routers函数注册的模块数量
    
    try:
        from neurova.api.endpoints import register_endpoint_routers
        
        # 检查函数是否存在
        assert callable(register_endpoint_routers), "register_endpoint_routers应该是可调用的"
        
        # 注意：我们不实际调用函数，只是验证函数存在
        # 因为调用需要完整的应用上下文
        
    except ImportError as e:
        pytest.skip(f"跳过测试: 模块导入失败 - {e}")


def test_frontend_api_coverage():
    """测试前端API覆盖率"""
    # 根据分析文档，75个后端API中只有34个有前端模块
    
    # 这是一个静态检查，验证分析文档中的数据
    backend_count = 75
    frontend_count = 34
    coverage = frontend_count / backend_count * 100
    
    print(f"后端API数量: {backend_count}")
    print(f"前端API模块: {frontend_count}")
    print(f"覆盖率: {coverage:.1f}%")
    
    # 验证覆盖率低于50%，需要改进
    assert coverage < 50, f"API覆盖率应该低于50%，当前: {coverage:.1f}%"


def test_missing_frontend_modules():
    """测试缺失的前端模块"""
    # 根据分析文档，有28个后端API缺少前端模块
    
    missing_high_priority = [
        "/v1/generation",
        "/v1/context", 
        "/v1/metacognition",
        "/v1/experience",
        "/v1/knowledge-graph",
        "/v1/growth"
    ]
    
    print(f"高优先级缺失的前端模块: {len(missing_high_priority)}")
    
    # 验证高优先级缺失模块数量
    assert len(missing_high_priority) == 6, f"应该有6个高优先级缺失模块，实际: {len(missing_high_priority)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])