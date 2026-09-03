"""
BUG CH-012 (P0): qq.py try:pass 导入错误测试

TDD RED phase: 验证 QQ 适配器正确导入 requests 库。

问题: try 块为空 (pass)，requests 从未导入，但 REQUESTS_AVAILABLE = True。
修复方向: 在 try 块内添加 `import requests`。
"""

import importlib
import sys


def _reload_qq_module():
    """重新导入 qq 模块以获取最新状态"""
    mods_to_remove = [k for k in sys.modules if k.startswith("neurova.channels.qq")]
    for k in mods_to_remove:
        del sys.modules[k]
    return importlib.import_module("neurova.channels.qq")


def test_qq_requests_available_flag_matches_actual_availability():
    """REQUESTS_AVAILABLE 标志必须准确反映 requests 库的实际可用性。"""
    try:
        import requests as _real_requests  # noqa: F401

        requests_installed = True
    except ImportError:
        requests_installed = False

    qq_mod = _reload_qq_module()

    assert qq_mod.REQUESTS_AVAILABLE == requests_installed, (
        f"REQUESTS_AVAILABLE={qq_mod.REQUESTS_AVAILABLE} "
        f"但 requests 实际可用性={requests_installed}"
    )


def test_qq_requests_module_accessible_when_flag_true():
    """当 REQUESTS_AVAILABLE=True 时，requests 必须在模块命名空间中可用。

    这是 BUG CH-012 的核心：try:pass 导致 requests 从未导入。
    """
    qq_mod = _reload_qq_module()

    if qq_mod.REQUESTS_AVAILABLE:
        assert hasattr(qq_mod, "requests"), (
            "REQUESTS_AVAILABLE=True 但 requests 未在模块命名空间中，"
            "后续代码调用 requests 会抛 NameError"
        )
        assert qq_mod.requests.__name__ == "requests"
