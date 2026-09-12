"""B-11 防复活锁存：AutoContextUpdater（memory_layer/auto_context_updater.py）保持已删除。

删除依据（2026-09-11 终账 B-11）：全仓 grep 零运行时消费方（仅自身定义与
专属旧测试 tests/unit/test_auto_context_updater_m14.py）。台账第五节：死代码
接线即周期 CPU 尖峰；接线前先删除。若未来恢复必须先接运行时消费方并带界。
"""

import importlib.util


def test_auto_context_updater_module_deleted():
    assert importlib.util.find_spec(
        "neurova.cognitive_layers.memory_layer.auto_context_updater"
    ) is None, "auto_context_updater.py 复活（B-11 已判定删除）"


def test_memory_layer_package_does_not_reexport_updater():
    from neurova.cognitive_layers import memory_layer

    for name in ("AutoContextUpdater", "ContextAutoUpdater"):
        assert not hasattr(memory_layer, name), f"{name} 不应被 memory_layer 导出"
