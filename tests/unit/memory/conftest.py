"""tests/unit/memory 共享夹具

配置单例隔离：MemorySettingsConfig 是进程级单例（get_instance 后固化），
任何测试对它的 update 都会泄漏到后续测试；且无 fixture 的测试可能读到
真实 data/memory_settings.json 的覆盖值。autouse 在每个测试前重置单例，
需要自定义配置的测试自行 get_memory_settings(tmp_path) 建隔离实例。
"""

import pytest

from neurova.cognitive_layers.memory_layer.settings_config import MemorySettingsConfig


@pytest.fixture(autouse=True)
def _reset_memory_settings_singleton():
    MemorySettingsConfig.reset_instance()
    yield
    MemorySettingsConfig.reset_instance()
