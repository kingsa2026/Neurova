"""对话记忆刷写必须读回真实存储， Silent success 不得出队。"""

from datetime import datetime

from neurova.cognitive_layers.memory_layer.conversation_buffer import (
    MemoryItem,
    MemoryWriteQueue,
)
from neurova.cognitive_layers.memory_layer.storage import MemoryStorage


def _item(content="需要持久化的对话记忆"):
    return MemoryItem(
        id="memory-1",
        content=content,
        timestamp=datetime.now(),
        classification="conversation",
    )


class SilentStorage:
    def save(self, **kwargs):
        return "missing-after-save"

    def get(self, memory_id):
        return None


def testFlushRequeuesWhenSavedIdCannotBeReadBack():
    queue = MemoryWriteQueue(storage=SilentStorage(), agent_id="a1")
    queue.enqueue(_item())

    assert queue.flush_to_storage() == 0
    assert queue.get_queue_size() == 1


def testFlushCountsReadableRealStorageWrite(tmp_path):
    storage = MemoryStorage(str(tmp_path))
    queue = MemoryWriteQueue(storage=storage, agent_id="a1")
    queue.enqueue(_item())

    assert queue.flush_to_storage() == 1
    assert queue.get_queue_size() == 0
    assert storage.count() == 1
