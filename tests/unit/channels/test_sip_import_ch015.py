"""
BUG CH-015 (P0): sip.py PYVOIP_AVAILABLE 标志错误测试

TDD RED phase: 验证 SIP 适配器正确导入 pyvoip 库。

问题: try 块为空，PYVOIP_AVAILABLE = True 但 pyvoip 从未导入。
       标志永远 True，即使 pyvoip 未安装。
修复方向: 在 try 块内添加 `import pyvoip`。
"""

import importlib
import sys


def _reload_sip_module():
    """重新导入 sip 模块以获取最新状态"""
    mods_to_remove = [k for k in sys.modules if k.startswith("neurova.channels.sip")]
    for k in mods_to_remove:
        del sys.modules[k]
    return importlib.import_module("neurova.channels.sip")


def test_sip_pyvoip_available_flag_matches_actual_availability():
    """PYVOIP_AVAILABLE 标志必须准确反映 pyvoip 库的实际可用性。

    BUG CH-015 核心：try 块为空导致 PYVOIP_AVAILABLE 永远为 True，
    即使 pyvoip 未安装。
    """
    try:
        import pyvoip as _real_pyvoip  # noqa: F401

        pyvoip_installed = True
    except ImportError:
        pyvoip_installed = False

    sip_mod = _reload_sip_module()

    assert sip_mod.PYVOIP_AVAILABLE == pyvoip_installed, (
        f"PYVOIP_AVAILABLE={sip_mod.PYVOIP_AVAILABLE} "
        f"但 pyvoip 实际可用性={pyvoip_installed}"
    )


def test_sip_pyvoip_module_accessible_when_flag_true():
    """当 PYVOIP_AVAILABLE=True 时，pyvoip 必须在模块命名空间中可用。"""
    sip_mod = _reload_sip_module()

    if sip_mod.PYVOIP_AVAILABLE:
        assert hasattr(sip_mod, "pyvoip"), (
            "PYVOIP_AVAILABLE=True 但 pyvoip 未在模块命名空间中，"
            "后续代码调用 pyvoip 会抛 NameError"
        )
        assert sip_mod.pyvoip.__name__ == "pyvoip"
