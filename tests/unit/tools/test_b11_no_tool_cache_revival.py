"""B-11 防复活锁存：ToolCache（tool_layers/tool_cache.py）保持已删除。

删除依据（2026-09-11 终账 B-11）：全仓 grep 零运行时实例化（仅自身定义、
__init__ 再导出、专属旧测试 tests/unit/tools/test_tool_cache.py 三类引用）。
L2/L3 缓存无界（台账第五节），接线前先删除；若未来要恢复必须带界并补
运行时消费方，届时同步删除本锁存测试。
"""

import importlib.util

import neurova.tool_layers as tool_layers_pkg


def test_tool_cache_module_deleted():
    assert importlib.util.find_spec("neurova.tool_layers.tool_cache") is None, (
        "tool_layers/tool_cache.py 复活（B-11 已判定删除）"
    )


def test_tool_layers_package_no_longer_reexports_tool_cache():
    for name in ("ToolCache", "CacheEntry"):
        assert not hasattr(tool_layers_pkg, name), f"{name} 不应再被 tool_layers 导出"
        assert name not in tool_layers_pkg.__all__, f"{name} 不应留在 tool_layers.__all__"
