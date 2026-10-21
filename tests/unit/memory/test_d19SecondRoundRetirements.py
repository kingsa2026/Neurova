"""D19 重做第 2 组退役守卫（§6-376）。

用户 2026-10-21 按推荐裁定：
- `memory_index`：隔离 tags 并进 `MemoryStorage.list_by_tags` 后退役；`text`/`ids`/隔离统计显式放弃。
- `vector_index_manager`：显式放弃异步索引（无延迟证据、无调用方）。
- `vector_search`：显式放弃持久化索引（活实现重建 p95 可接受＋已有嵌入缓存）。
"""
import importlib.util


def test_memoryIndexModuleIsGone():
    assert importlib.util.find_spec(
        "neurova.cognitive_layers.memory_layer.memory_index") is None


def test_vectorIndexManagerModuleIsGone():
    assert importlib.util.find_spec(
        "neurova.cognitive_layers.memory_layer.vector_index_manager") is None


def test_vectorSearchModuleIsGone():
    assert importlib.util.find_spec(
        "neurova.cognitive_layers.memory_layer.vector_search") is None
