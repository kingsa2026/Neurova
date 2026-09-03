"""
BUG CH-013 (P0): qqbot.py import re 误写测试

TDD RED phase: 验证 QQBot 适配器正确导入 requests 库。

问题: line 26 `import re` 误写（应为 `import requests`），re 已在 line 19 导入。
       requests 从未导入，但 REQUESTS_AVAILABLE = True（因为 import re 总会成功）。
修复方向: 将 `import re` 改为 `import requests`。
"""

import importlib
import sys


def _reload_qqbot_module():
    """重新导入 qqbot 模块以获取最新状态"""
    mods_to_remove = [k for k in sys.modules if k.startswith("neurova.channels.qqbot")]
    for k in mods_to_remove:
        del sys.modules[k]
    return importlib.import_module("neurova.channels.qqbot")


def test_qqbot_requests_available_flag_matches_actual_availability():
    """REQUESTS_AVAILABLE 标志必须准确反映 requests 库（非 re 库）的实际可用性。

    BUG CH-013 核心错误：try 块内 `import re`（stdlib，永远成功）导致
    REQUESTS_AVAILABLE 永远为 True，但 requests 实际未导入。
    """
    try:
        import requests as _real_requests  # noqa: F401

        requests_installed = True
    except ImportError:
        requests_installed = False

    qqbot_mod = _reload_qqbot_module()

    assert qqbot_mod.REQUESTS_AVAILABLE == requests_installed, (
        f"REQUESTS_AVAILABLE={qqbot_mod.REQUESTS_AVAILABLE} "
        f"但 requests 实际可用性={requests_installed}"
    )


def test_qqbot_requests_module_accessible_when_flag_true():
    """当 REQUESTS_AVAILABLE=True 时，requests 必须在模块命名空间中可用。

    这是 BUG CH-013 的核心：`import re` 误写导致 requests 从未导入。
    """
    qqbot_mod = _reload_qqbot_module()

    if qqbot_mod.REQUESTS_AVAILABLE:
        assert hasattr(qqbot_mod, "requests"), (
            "REQUESTS_AVAILABLE=True 但 requests 未在模块命名空间中，"
            "后续代码调用 requests 会抛 NameError"
        )
        assert qqbot_mod.requests.__name__ == "requests"
