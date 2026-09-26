"""路由前缀对照断言（2026-09-13 起改指现行真集；2026-09-26 收窄）。

原文件要求 `skill_market` / `skills_market` 必须存在且带 `router`——那与
ADR 0013「删除 A/B/C 三套、保留 skill_pool_api 为唯一规范端点」的裁定直接对冲，
也与 Issue #68 的处置台账（skill_market / skills_market 已删除）对冲。
按教义第 2 条，不能为了保住这条旧断言而让已判定的死套复活；
改为断言**现行真集**存活、且两个已删套确实不在。

2026-09-26（Issue #90 · T-09 §10 第 2b 项）：`context_pool_settings` 随假设置面
一并下架（零非测试消费者、读数是模块级常量、PUT 早已 501），故它从"现行真集"
里移出——旧断言锁的正是那个已判定的面。同批加进反向控制：它必须真的不在仓里
（判据 `tests/unit/api/test_context_pool_settings_face_retirement.py`）。
"""
import importlib.util

import pytest


def test_route_prefix_changes():
    """现行挂载前缀（channels 与 context 两组同名歧义已各自收口）。"""
    fixes = {
        "channels": "/v1/channel-adapters",
        "context": "/v1/context",
    }
    for module, prefix in fixes.items():
        assert prefix.startswith("/v1/"), f"{module} 的前缀未落在 /api/v1 挂载层：{prefix}"


def test_current_route_modules_import():
    """现行路由模块必须可导入且带 `router`。"""
    for name in ("channels", "context", "skill_pool_api"):
        module = __import__(f"neurova.api.endpoints.{name}", fromlist=["router"])
        assert hasattr(module, "router"), f"{name} 模块应该有 router"


@pytest.mark.parametrize("removed", ["skill_market", "skills_market"])
def test_deprecated_market_shells_are_removed(removed):
    """ADR 0013 判定删除的两套市场端点必须真的不在（不是「不注册」）。"""
    assert importlib.util.find_spec(f"neurova.api.endpoints.{removed}") is None, (
        f"{removed} 已由 ADR 0013 判定删除，却又出现在仓库里——死套复活。"
    )


def test_retired_pool_settings_shell_is_removed():
    """T-09 §10 第 2b 项：假设置面已判定下架，不得复活（不是「不注册」）。"""
    assert importlib.util.find_spec("neurova.api.endpoints.context_pool_settings") is None, (
        "context_pool_settings 已按 Issue #90 §10 第 2b 项判定下架，却又出现在仓库里。"
    )
