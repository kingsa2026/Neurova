"""M-06 / M-07 / M-09 锁覆盖修复的确定性回归测试（线程安全契约）。

根因：共享内存结构在锁外被并发读写 ——
- M-06（manager.py）：recall / get_memories / get_stats 在 `with self._lock:`
  之前调用 `_scoped_memories()` / `_agent_memories()`（迭代 self._memories.values()），
  与 remember/forget 的字典增删竞态 → RuntimeError: dictionary changed size。
- M-07（semantic_search.py）：_keyword_index 全方法无锁，remove_memory_index
  边迭代边 del → 并发 RuntimeError。
- M-09（cognitive_storage_engine.py）：_l0_buffer / _vector_index 无任何锁保护，
  store / retrieve / update_temperature / get_statistics / flush 并发竞态。

确定性策略（沿用 test_thread_safety_bugs.py）：主线程持锁，子线程调用方法应阻塞
（证明方法在临界区内取锁）。M-06 额外用 `RLock._is_owned()` 验证基集构造
发生在锁内（而非锁外、仅方法体内部才取锁）。CPython GIL 下纯竞态不可复现，
故用锁契约做确定性断言。
"""

import threading
import time
import uuid

from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
    CognitiveStorageEngine,
    UnifiedMemoryNode,
)
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.semantic_search import SemanticSearch


def _make_manager(agent_id="m060709"):
    uid = f"{agent_id}_{uuid.uuid4().hex[:8]}"
    return MemoryManager(db_path=":memory:", agent_id=uid)


class TestM06ManagerScopedMemoriesInsideLock:
    """M-06：recall/get_memories/get_stats 的基集必须在锁内构造。

    旧代码在 `with self._lock:` 之前执行 `_scoped_memories()`（迭代共享 dict），
    与 remember/forget 的增删竞态。修复：把 `base = ...` 移入锁内。
    用 `_is_owned()` 确定性验证——基集构造瞬间，当前线程必须持有 self._lock。
    """

    def _assert_base_built_inside_lock(self, mgr, method):
        mgr.remember(content="x", temperature=50.0)
        captured = {}
        orig = mgr._scoped_memories

        def patched():
            # 基集构造发生在锁内 → 当前线程必须持有锁
            captured["owned"] = mgr._lock._is_owned()
            return orig()

        mgr._scoped_memories = patched

        mgr._lock.acquire()
        try:
            done = threading.Event()

            def worker():
                try:
                    method()
                finally:
                    done.set()

            t = threading.Thread(target=worker)
            t.start()
            time.sleep(0.1)  # 让 worker 触达基集构造点
            mgr._lock.release()
            done.wait(timeout=2.0)
        finally:
            try:
                mgr._lock.release()
            except RuntimeError:
                pass
        t.join(timeout=1.0)
        assert captured.get("owned") is True, (
            "M-06 未修复：基集构造在锁外执行（应为锁内）"
        )

    def test_recall_builds_base_inside_lock(self):
        mgr = _make_manager()
        self._assert_base_built_inside_lock(mgr, lambda: mgr.recall(query="x"))

    def test_get_memories_builds_base_inside_lock(self):
        mgr = _make_manager()
        self._assert_base_built_inside_lock(mgr, lambda: mgr.get_memories())

    def test_get_stats_builds_base_inside_lock(self):
        mgr = _make_manager()
        self._assert_base_built_inside_lock(mgr, lambda: mgr.get_stats())


class TestM07SemanticSearchIndexLock:
    """M-07：_keyword_index 的所有读写必须在 _index_lock 内。

    旧代码无锁，remove_memory_index 边迭代边 del → 并发 RuntimeError。
    修复：build/upsert/remove/search 全部 `with self._index_lock:`。
    确定性验证：持 _index_lock 时子线程调用方法应阻塞。
    """

    def _make_ss(self):
        ss = SemanticSearch(use_embedding=False)
        ss.build_keyword_index([{"id": "m1", "content": "hello world"}])
        return ss

    def _assert_method_blocks_on_index_lock(self, ss, method):
        assert hasattr(ss, "_index_lock"), "M-07 未修复：SemanticSearch 缺少 _index_lock"
        ss._index_lock.acquire()
        try:
            done = threading.Event()

            def worker():
                try:
                    method()
                finally:
                    done.set()

            t = threading.Thread(target=worker)
            t.start()
            # 旧代码未取锁 → worker 立即完成；修复后 → 阻塞
            done.wait(timeout=0.5)
            assert not done.is_set(), (
                "M-07 未修复：方法未获取 _index_lock（worker 未阻塞）"
            )
            ss._index_lock.release()
            done.wait(timeout=2.0)
            assert done.is_set(), "M-07：释放锁后方法未完成"
        finally:
            try:
                ss._index_lock.release()
            except RuntimeError:
                pass
        t.join(timeout=1.0)

    def test_search_by_keywords_acquires_lock(self):
        ss = self._make_ss()
        self._assert_method_blocks_on_index_lock(ss, lambda: ss.search_by_keywords("hello"))

    def test_remove_memory_index_acquires_lock(self):
        ss = self._make_ss()
        self._assert_method_blocks_on_index_lock(ss, lambda: ss.remove_memory_index("m1"))

    def test_upsert_memory_index_acquires_lock(self):
        ss = self._make_ss()
        self._assert_method_blocks_on_index_lock(
            ss, lambda: ss.upsert_memory_index({"id": "m2", "content": "foo bar"})
        )


class TestM09StorageEngineBufferLock:
    """M-09：_l0_buffer / _vector_index 的所有访问必须在 _buffer_lock 内。

    旧代码 store/retrieve/update_temperature/get_statistics/flush 对内存态无锁，
    并发竞态。修复：新增 _buffer_lock 并保护全部内存态访问。
    确定性验证：持 _buffer_lock 时子线程调用方法应阻塞。
    """

    def _make_engine(self, tmp_path):
        return CognitiveStorageEngine(agent_id="m09", data_dir=str(tmp_path / "store"))

    def _assert_method_blocks_on_buffer_lock(self, engine, method):
        assert hasattr(engine, "_buffer_lock"), "M-09 未修复：引擎缺少 _buffer_lock"
        engine._buffer_lock.acquire()
        try:
            done = threading.Event()

            def worker():
                try:
                    method()
                finally:
                    done.set()

            t = threading.Thread(target=worker)
            t.start()
            done.wait(timeout=0.5)
            assert not done.is_set(), (
                "M-09 未修复：方法未获取 _buffer_lock（worker 未阻塞）"
            )
            engine._buffer_lock.release()
            done.wait(timeout=2.0)
            assert done.is_set(), "M-09：释放锁后方法未完成"
        finally:
            try:
                engine._buffer_lock.release()
            except RuntimeError:
                pass
        t.join(timeout=1.0)

    def test_store_acquires_buffer_lock(self, tmp_path):
        engine = self._make_engine(tmp_path)
        node = UnifiedMemoryNode(content="hi")
        self._assert_method_blocks_on_buffer_lock(engine, lambda: engine.store(node))

    def test_retrieve_acquires_buffer_lock(self, tmp_path):
        engine = self._make_engine(tmp_path)
        self._assert_method_blocks_on_buffer_lock(engine, lambda: engine.retrieve("hi"))

    def test_update_temperature_acquires_buffer_lock(self, tmp_path):
        engine = self._make_engine(tmp_path)
        node = UnifiedMemoryNode(content="hi")
        engine.store(node)
        self._assert_method_blocks_on_buffer_lock(
            engine, lambda: engine.update_temperature(node.id, 1.0)
        )

    def test_get_statistics_acquires_buffer_lock(self, tmp_path):
        engine = self._make_engine(tmp_path)
        self._assert_method_blocks_on_buffer_lock(engine, lambda: engine.get_statistics())
