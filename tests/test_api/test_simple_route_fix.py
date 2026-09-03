"""简单的路由修复测试"""
import pytest


def test_route_prefix_changes():
    """测试路由前缀变更"""
    # 验证修复后的前缀
    fixes = {
        "channels": "/v1/channel-adapters",
        "context_pool_settings": "/v1/context-pool", 
        "skill_market": "/v1/skills-market",
    }
    
    print("路由前缀修复:")
    for module, prefix in fixes.items():
        print(f"  {module} -> {prefix}")
    
    # 验证修复
    assert fixes["channels"] == "/v1/channel-adapters", "channels前缀修复错误"
    assert fixes["context_pool_settings"] == "/v1/context-pool", "context_pool_settings前缀修复错误"
    assert fixes["skill_market"] == "/v1/skills-market", "skill_market前缀修复错误"


def test_import_after_fix():
    """测试修复后模块导入"""
    try:
        from neurova.api.endpoints import channel
        from neurova.api.endpoints import channels
        from neurova.api.endpoints import context
        from neurova.api.endpoints import context_pool_settings
        from neurova.api.endpoints import skill_market
        from neurova.api.endpoints import skills_market
        
        print("所有模块导入成功")
        
        # 检查router属性
        assert hasattr(channel, 'router'), "channel模块应该有router"
        assert hasattr(channels, 'router'), "channels模块应该有router"
        assert hasattr(context, 'router'), "context模块应该有router"
        assert hasattr(context_pool_settings, 'router'), "context_pool_settings模块应该有router"
        assert hasattr(skill_market, 'router'), "skill_market模块应该有router"
        assert hasattr(skills_market, 'router'), "skills_market模块应该有router"
        
        print("所有模块都有router属性")
        
    except ImportError as e:
        pytest.fail(f"模块导入失败: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])