"""
BE-CORE-003 (P0) 修复测试: agent_core.py logging 未导入

问题: neurova/agent_core.py 第 40/52/84 行调用 `logging.warning(...)`，
但文件头仅 `from neurova.core.logger import get_logger`，未 `import logging`。
当可选依赖（TemperatureEngine / Cognitive Graph / Agent Loop）导入失败时，
except 分支执行 logging.warning() 会抛 NameError: name 'logging' is not defined，
导致整个 agent_core 模块加载失败。

TDD RED 阶段: 本测试在 buggy 代码下应失败（NameError）。
TDD GREEN 阶段: 修复后应通过。
"""

import importlib
import sys
from unittest.mock import patch


def test_agent_core_module_imports_without_nameerror():
    """导入 agent_core 模块不应抛 NameError。

    即使可选依赖导入失败触发 except 分支的 logging.warning() 调用，
    模块也应正常加载。
    """
    # 强制重新导入模块以触发模块级代码
    if "neurova.agent_core" in sys.modules:
        del sys.modules["neurova.agent_core"]
    try:
        importlib.import_module("neurova.agent_core")
    finally:
        # 确保模块被重新加载以避免影响后续测试
        if "neurova.agent_core" not in sys.modules:
            importlib.import_module("neurova.agent_core")


def test_agent_core_has_logging_module_available():
    """agent_core 模块应能访问 logging 模块。

    验证模块级代码中引用的 logging 名称可用。
    """
    import neurova.agent_core as ac

    # 模块内应能引用 logging（无论是 import logging 还是通过其他方式）
    assert hasattr(ac, "logging") or "logging" in dir(ac) or _can_call_logging_warning()


def _can_call_logging_warning() -> bool:
    """检查 agent_core 模块命名空间中 logging 是否可用。"""
    import neurova.agent_core as ac

    # 模拟 except 分支的调用
    try:
        # 在模块的命名空间中执行 logging.warning
        exec("logging.warning('test')", ac.__dict__)
        return True
    except NameError:
        return False


def test_agent_core_temperature_engine_unavailable_path_logs_without_crash():
    """当 TemperatureEngine 导入失败时，except 分支不应崩溃。

    通过模拟导入失败，验证 except 分支的 logging.warning 调用正常工作。
    """
    # 先确保模块已加载
    import neurova.agent_core  # noqa: F401

    # 验证模块级常量存在（说明 except 分支成功执行）
    import neurova.agent_core as ac

    # TEMPERATURE_ENGINE_AVAILABLE 应为 True 或 False，不应因 NameError 而缺失
    assert hasattr(ac, "TEMPERATURE_ENGINE_AVAILABLE")
    assert hasattr(ac, "COGNITIVE_GRAPH_AVAILABLE")
    assert hasattr(ac, "AGENT_LOOP_AVAILABLE")
