"""
BUG CH-014 (P0): qclaw.py try:pass + logging 未导入测试

TDD RED phase: 验证 QClaw 适配器正确导入 requests 库且不触发 logging NameError。

问题:
1. try 块为空 (pass)，requests 从未导入，但 REQUESTS_AVAILABLE = True
2. except 块使用 logging.warning(...) 但仅导入 get_logger，未 import logging
   当 requests 未安装时，except 块会抛 NameError: name 'logging' is not defined

修复方向:
- 在 try 块内添加 `import requests`
- 将 `logging.warning(...)` 改为 `logger.warning(...)`（用已有的 get_logger 实例）
"""

import importlib
import sys


def _reload_qclaw_module():
    """重新导入 qclaw 模块以获取最新状态"""
    mods_to_remove = [k for k in sys.modules if k.startswith("neurova.channels.qclaw")]
    for k in mods_to_remove:
        del sys.modules[k]
    return importlib.import_module("neurova.channels.qclaw")


def test_qclaw_requests_available_flag_matches_actual_availability():
    """REQUESTS_AVAILABLE 标志必须准确反映 requests 库的实际可用性。"""
    try:
        import requests as _real_requests  # noqa: F401

        requests_installed = True
    except ImportError:
        requests_installed = False

    qclaw_mod = _reload_qclaw_module()

    assert qclaw_mod.REQUESTS_AVAILABLE == requests_installed, (
        f"REQUESTS_AVAILABLE={qclaw_mod.REQUESTS_AVAILABLE} "
        f"但 requests 实际可用性={requests_installed}"
    )


def test_qclaw_requests_module_accessible_when_flag_true():
    """当 REQUESTS_AVAILABLE=True 时，requests 必须在模块命名空间中可用。"""
    qclaw_mod = _reload_qclaw_module()

    if qclaw_mod.REQUESTS_AVAILABLE:
        assert hasattr(qclaw_mod, "requests"), (
            "REQUESTS_AVAILABLE=True 但 requests 未在模块命名空间中，"
            "后续代码调用 requests 会抛 NameError"
        )
        assert qclaw_mod.requests.__name__ == "requests"


def test_qclaw_module_has_logger_instance():
    """模块必须有可用的 logger 实例（用于替代 logging.warning 调用）。

    BUG CH-014 的第二个问题：except 块用 logging.warning 但未 import logging。
    修复后应使用项目统一的 logger 实例。
    """
    qclaw_mod = _reload_qclaw_module()

    assert hasattr(qclaw_mod, "logger"), "模块缺少 logger 实例"
    # logger 必须有 warning 方法
    assert hasattr(qclaw_mod.logger, "warning"), "logger 实例缺少 warning 方法"
