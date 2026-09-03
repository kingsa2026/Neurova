"""
BUG CH-016 (P0): dingtalk.py dingtalk_stream 未导入测试

TDD RED phase: 验证 DingTalk 适配器正确处理 dingtalk_stream 依赖。

问题: 使用 `dingtalk_stream.Credential(...)` 和
       `dingtalk_stream.DingtalkStreamClient(...)` 但无 import 语句。
       调用 _connect_stream() 时会抛 NameError。
修复方向: 添加 `import dingtalk_stream`（在 try/except 内）。
"""

import importlib
import sys


def _reload_dingtalk_module():
    """重新导入 dingtalk 模块以获取最新状态"""
    mods_to_remove = [
        k for k in sys.modules if k.startswith("neurova.channels.dingtalk")
    ]
    for k in mods_to_remove:
        del sys.modules[k]
    return importlib.import_module("neurova.channels.dingtalk")


def test_dingtalk_module_imports_without_name_error():
    """模块必须能成功导入，不因缺失 dingtalk_stream 而崩溃。

    BUG CH-016 核心：使用 dingtalk_stream 但未 import，
    模块导入时虽不报错（因为只在方法内使用），
    但调用 _connect_stream() 会抛 NameError。
    """
    # 这个测试主要验证模块可以导入
    dingtalk_mod = _reload_dingtalk_module()
    assert dingtalk_mod is not None


def test_dingtalk_has_stream_availability_flag():
    """模块必须有 dingtalk_stream 可用性标志。

    修复后应添加 DINGTALK_STREAM_AVAILABLE 标志，
    以便代码在调用前检查依赖是否可用。
    """
    dingtalk_mod = _reload_dingtalk_module()
    assert hasattr(dingtalk_mod, "DINGTALK_STREAM_AVAILABLE"), (
        "模块缺少 DINGTALK_STREAM_AVAILABLE 标志，"
        "应在 try/except 内 import dingtalk_stream 并设置标志"
    )


def test_dingtalk_stream_flag_matches_actual_availability():
    """DINGTALK_STREAM_AVAILABLE 标志必须准确反映 dingtalk_stream 库的可用性。"""
    try:
        import dingtalk_stream as _real_dt  # noqa: F401

        dt_installed = True
    except ImportError:
        dt_installed = False

    dingtalk_mod = _reload_dingtalk_module()

    assert dingtalk_mod.DINGTALK_STREAM_AVAILABLE == dt_installed, (
        f"DINGTALK_STREAM_AVAILABLE={dingtalk_mod.DINGTALK_STREAM_AVAILABLE} "
        f"但 dingtalk_stream 实际可用性={dt_installed}"
    )


def test_dingtalk_stream_module_accessible_when_flag_true():
    """当 DINGTALK_STREAM_AVAILABLE=True 时，dingtalk_stream 必须在模块命名空间中可用。"""
    dingtalk_mod = _reload_dingtalk_module()

    if dingtalk_mod.DINGTALK_STREAM_AVAILABLE:
        assert hasattr(dingtalk_mod, "dingtalk_stream"), (
            "DINGTALK_STREAM_AVAILABLE=True 但 dingtalk_stream 未在模块命名空间中，"
            "调用 _connect_stream() 会抛 NameError"
        )
        assert dingtalk_mod.dingtalk_stream.__name__ == "dingtalk_stream"
