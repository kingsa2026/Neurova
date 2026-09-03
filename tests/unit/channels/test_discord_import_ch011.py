"""
BUG CH-011 (P0): discord.py try:pass 导入错误测试

TDD RED phase: 验证 discord 适配器正确导入 requests 库。

问题: try 块为空 (pass)，requests 从未导入，但 REQUESTS_AVAILABLE = True。
修复方向: 在 try 块内添加 `import requests`。
"""

import importlib
import sys

import pytest


def _reload_discord_module():
    """重新导入 discord 模块以获取最新状态"""
    # 清除缓存以避免上次导入的副作用
    mods_to_remove = [k for k in sys.modules if k.startswith("neurova.channels.discord")]
    for k in mods_to_remove:
        del sys.modules[k]
    return importlib.import_module("neurova.channels.discord")


def test_discord_requests_available_flag_matches_actual_availability():
    """REQUESTS_AVAILABLE 标志必须准确反映 requests 库的实际可用性。

    若 requests 已安装，REQUESTS_AVAILABLE 应为 True；
    若 requests 未安装，REQUESTS_AVAILABLE 应为 False。
    """
    try:
        import requests as _real_requests  # noqa: F401

        requests_installed = True
    except ImportError:
        requests_installed = False

    discord_mod = _reload_discord_module()

    assert discord_mod.REQUESTS_AVAILABLE == requests_installed, (
        f"REQUESTS_AVAILABLE={discord_mod.REQUESTS_AVAILABLE} "
        f"但 requests 实际可用性={requests_installed}"
    )


def test_discord_requests_module_accessible_when_flag_true():
    """当 REQUESTS_AVAILABLE=True 时，requests 必须在模块命名空间中可用。

    这是 BUG CH-011 的核心：try:pass 导致 requests 从未导入，
    但 REQUESTS_AVAILABLE=True，后续代码使用 requests 会抛 NameError。
    """
    discord_mod = _reload_discord_module()

    if discord_mod.REQUESTS_AVAILABLE:
        assert hasattr(discord_mod, "requests"), (
            "REQUESTS_AVAILABLE=True 但 requests 未在模块命名空间中，"
            "后续代码调用 requests 会抛 NameError"
        )
        # 确认是真正的 requests 库，而非其他对象
        assert discord_mod.requests.__name__ == "requests"
