"""M-24 回归测试：wait_for_completion 感知 in-flight 批次。

根因：vector_index_manager.py
- `wait_for_completion` 只查 `if not self._queue`，而 worker 取批时已把
  批次从队列弹出（in-flight 不可见）→ 处理中即过早返回 True；
- worker `Event.clear()` 在多 worker 下会丢掉其他 worker 尚未消费的唤醒。

修复后契约：
- worker 取批时锁内 in-flight += len(batch)，_process_operation 完成时 -1；
  wait_for_completion 需队列空且 in-flight==0 才返回 True；
- Event 仅在锁内确认队列为空时 clear（保留 1s 轮询兜底）。
"""

import threading
import time

import pytest

from neurova.cognitive_layers.memory_layer.vector_index_manager import (
    OperationType,
    VectorIndexManager,
)


@pytest.fixture()
def manager():
    mgr = VectorIndexManager(
        state_path=None,
        num_workers=1,
        batch_size=8,
        auto_start=True,
    )
    yield mgr
    mgr.shutdown(wait=False)


class TestM24WaitForCompletionInFlight:
    def test_in_flight_batch_not_reported_complete(self, manager):
        release = threading.Event()
        add_started = threading.Event()

        def slow_add(memory_id, embedding, metadata):
            add_started.set()
            release.wait(timeout=10.0)
            return True

        manager._add_fn = slow_add
        manager.add_memory("mem-1", [0.1, 0.2], {})

        # 等待 worker 把批次弹出并进入处理（in-flight）
        assert add_started.wait(timeout=5.0), "worker 未开始处理操作"
        time.sleep(0.2)

        # 批次已弹出（队列空）但仍处理中 → 不得返回 True
        assert manager.wait_for_completion(timeout=1.0) is False, (
            "wait_for_completion 只看队列，in-flight 批次被过早判定完成（M-24 未修复）"
        )

        release.set()
        assert manager.wait_for_completion(timeout=5.0) is True, (
            "操作真正完成后应返回 True"
        )

    def test_queue_only_operation_wait_works(self, manager):
        done = threading.Event()

        def quick_add(memory_id, embedding, metadata):
            done.set()
            return True

        manager._add_fn = quick_add
        manager.add_memory("mem-2", [0.3], {})
        assert manager.wait_for_completion(timeout=5.0) is True
        assert done.is_set()

    def test_operation_type_values(self):
        # 防呆：确保导入契约未漂移
        assert OperationType.ADD.value == "add"
