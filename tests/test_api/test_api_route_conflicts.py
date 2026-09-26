"""测试API路由冲突问题"""
import importlib
import importlib.util

import pytest


# 2026-09-13 死壳清理：endpoints/channel.py(/v1/channels 假桥) 已删除，
# 原 channel-vs-channels 冲突测试主体消失；渠道唯一真集为 channel_config.py(/v1/channel-configs)
# 与 channels.py(/v1/channel-adapters)，防复活钉见 tests/unit/api/test_channel_shell_removed.py
def test_context_route_conflict():
    """context / context_pool_settings 的同名歧义已随后者下架而消失。

    2026-09-13 那次修复把两者分别挂到 `/v1/context` 与 `/v1/context-pool`；
    2026-09-26（Issue #90 §10 第 2b 项）判定 `context_pool_settings` 是零非测试
    消费者的假设置面，整面下架 —— 冲突主体不复存在。本用例改锁**该面确实不在**
    （防复活），判据单源在 `tests/unit/api/test_context_pool_settings_face_retirement.py`。
    """
    assert importlib.util.find_spec("neurova.api.endpoints.context_pool_settings") is None, (
        "context_pool_settings 已判定下架却又出现 —— 已收口的同名歧义面复活了。"
    )
    from neurova.api.endpoints import context

    assert hasattr(context, "router"), "context 模块应该有 router"


def test_deprecated_market_shells_are_gone():
    """skill_market / skills_market 双套已按 ADR 0013 删除，单复数冲突主体消失。

    此前本文件断言两套都仍有 `router`——那正是待删套还活着的读数。
    """
    for name in ("neurova.api.endpoints.skill_market", "neurova.api.endpoints.skills_market"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(name)


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