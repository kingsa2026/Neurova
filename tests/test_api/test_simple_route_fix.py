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
    from neurova.api.endpoints import channels
    from neurova.api.endpoints import context
    from neurova.api.endpoints import context_pool_settings

    # 检查router属性
    assert hasattr(channels, 'router'), "channels模块应该有router"
    assert hasattr(context, 'router'), "context模块应该有router"
    assert hasattr(context_pool_settings, 'router'), "context_pool_settings模块应该有router"


def test_deprecated_market_modules_are_retired():
    """ADR 0013 判定的待删两套（skill_market / skills_market）已按该 ADR 删除。

    此前本文件断言两套仍有 `router`，那是「已废弃却留着入口」的形态——
    规范端点只有 `skill_pool_api.py`（/api/v1/skill-pool）。
    """
    import importlib

    for name in ("neurova.api.endpoints.skill_market", "neurova.api.endpoints.skills_market"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(name)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])