"""路由前缀对照断言（2026-09-13 起改指现行真集）。

原文件要求 `skill_market` / `skills_market` 必须存在且带 `router`——那与
ADR 0013「删除 A/B/C 三套、保留 skill_pool_api 为唯一规范端点」的裁定直接对冲，
也与 Issue #68 的处置台账（skill_market / skills_market 已删除）对冲。
按教义第 2 条，不能为了保住这条旧断言而让已判定的死套复活；
改为断言**现行真集**存活、且两个已删套确实不在。
"""
import importlib.util

import pytest


def test_route_prefix_changes():
    """现行挂载前缀（channels 与 context 两组同名歧义已各自收口）。"""
    fixes = {
        "channels": "/v1/channel-adapters",
        "context_pool_settings": "/v1/context-pool",
    }
    for module, prefix in fixes.items():
        assert prefix.startswith("/v1/"), f"{module} 的前缀未落在 /api/v1 挂载层：{prefix}"


def test_current_route_modules_import():
    """现行路由模块必须可导入且带 `router`。"""
    for name in ("channels", "context", "context_pool_settings", "skill_pool_api"):
        module = __import__(f"neurova.api.endpoints.{name}", fromlist=["router"])
        assert hasattr(module, "router"), f"{name} 模块应该有 router"


@pytest.mark.parametrize("removed", ["skill_market", "skills_market"])
def test_deprecated_market_shells_are_removed(removed):
    """ADR 0013 判定删除的两套市场端点必须真的不在（不是「不注册」）。"""
    assert importlib.util.find_spec(f"neurova.api.endpoints.{removed}") is None, (
        f"{removed} 已由 ADR 0013 判定删除，却又出现在仓库里——死套复活。"
    )
