"""ReadSessionStore 单元测试 —— 跨域续读游标的内存存储。

覆盖：
- create/read 分片切片语义（首片 / 续片 / 读尽 / 显式 offset 重读）
- 游标推进：不带 offset 续读时按 chunk_size 顺序前进
- TTL 过期（懒清理）与 LRU 驱逐（max_sessions 上界）
- 单例 get/reset 工厂
- 线程安全冒烟（并发续读不越界不重复）
"""

import threading

import pytest

from neurova.core.read_sessions import ReadSessionStore, get_read_session_store, reset_read_session_store


@pytest.fixture(autouse=True)
def _isolate_store():
    reset_read_session_store()
    yield
    reset_read_session_store()


class TestCreateAndRead:
    def test_first_chunk_and_cursor(self):
        store = ReadSessionStore()
        text = "A" * 250 + "B" * 250
        sess = store.create(domain="browser_read", url="https://e.com/a", title="t", text=text, chunk_size=100)

        first = store.read(sess.session_id)
        assert first is not None
        assert first["text"] == "A" * 100
        assert first["offset"] == 0
        assert first["next_offset"] == 100
        assert first["can_continue"] is True
        assert first["total_length"] == 500

    def test_sequential_chunks_advance_cursor(self):
        store = ReadSessionStore()
        sess = store.create(domain="dom_read", url="https://e.com/b", title="t", text="x" * 350, chunk_size=100)

        assert store.read(sess.session_id)["offset"] == 0
        second = store.read(sess.session_id)
        assert second["offset"] == 100
        third = store.read(sess.session_id)
        assert third["offset"] == 200

    def test_last_chunk_can_continue_false(self):
        store = ReadSessionStore()
        sess = store.create(domain="browser_read", url="https://e.com/c", title="t", text="y" * 250, chunk_size=100)

        chunks = [store.read(sess.session_id) for _ in range(3)]
        assert all(c["can_continue"] for c in chunks[:2])
        assert chunks[2]["can_continue"] is False
        assert chunks[2]["next_offset"] is None
        assert len(chunks[2]["text"]) == 50

    def test_read_past_end_returns_empty(self):
        store = ReadSessionStore()
        sess = store.create(domain="dom_read", url="https://e.com/d", title="t", text="z" * 50, chunk_size=100)

        for _ in range(2):
            store.read(sess.session_id)
        tail = store.read(sess.session_id)
        assert tail["text"] == ""
        assert tail["can_continue"] is False

    def test_explicit_offset_rereads(self):
        store = ReadSessionStore()
        text = "0123456789" * 30
        sess = store.create(domain="browser_read", url="https://e.com/e", title="t", text=text, chunk_size=100)

        again = store.read(sess.session_id, offset=100)
        assert again["text"] == text[100:200]

    def test_explicit_offset_does_not_break_cursor_sequence(self):
        """显式 offset 重读后，下一次不带 offset 仍按上次游标前进"""
        store = ReadSessionStore()
        text = "q" * 400
        sess = store.create(domain="dom_read", url="https://e.com/f", title="t", text=text, chunk_size=100)

        store.read(sess.session_id)                       # 游标 → 100
        store.read(sess.session_id, offset=0)             # 重读首片，不影响游标
        third = store.read(sess.session_id)
        assert third["offset"] == 100

    def test_negative_offset_clamped(self):
        store = ReadSessionStore()
        sess = store.create(domain="browser_read", url="https://e.com/g", title="t", text="n" * 300, chunk_size=100)

        chunk = store.read(sess.session_id, offset=-5)
        assert chunk["offset"] == 0

    def test_metadata_roundtrip(self):
        store = ReadSessionStore()
        sess = store.create(
            domain="dom_read", url="https://e.com/h", title="标题", text="m" * 200, chunk_size=50,
            target_id="tab_abc", generation=3,
        )
        got = store.get(sess.session_id)
        assert got.url == "https://e.com/h"
        assert got.title == "标题"
        assert got.target_id == "tab_abc"
        assert got.generation == 3
        assert got.domain == "dom_read"


class TestExpiryAndEviction:
    def test_ttl_expiry_lazy(self, monkeypatch):
        import neurova.core.read_sessions as rs_mod

        store = ReadSessionStore(ttl_seconds=60.0)
        sess = store.create(domain="browser_read", url="https://e.com/i", title="t", text="a", chunk_size=10)

        future = rs_mod._now() + 61.0
        monkeypatch.setattr(rs_mod, "_now", lambda: future)
        assert store.get(sess.session_id) is None
        assert store.read(sess.session_id) is None

    def test_lru_eviction_at_capacity(self):
        store = ReadSessionStore(max_sessions=3)
        ids = [
            store.create(domain="browser_read", url=f"https://e.com/{i}", title="t", text="a" * 30, chunk_size=10).session_id
            for i in range(4)
        ]
        # 最早创建的会话被驱逐
        assert store.get(ids[0]) is None
        assert store.get(ids[3]) is not None

    def test_access_refreshes_lru(self):
        store = ReadSessionStore(max_sessions=3)
        s0 = store.create(domain="browser_read", url="https://e.com/0", title="t", text="a" * 30, chunk_size=10)
        store.create(domain="browser_read", url="https://e.com/1", title="t", text="a" * 30, chunk_size=10)
        store.create(domain="browser_read", url="https://e.com/2", title="t", text="a" * 30, chunk_size=10)

        store.get(s0.session_id)  # 触摸最老会话 → 移到队尾
        s3 = store.create(domain="browser_read", url="https://e.com/3", title="t", text="a" * 30, chunk_size=10)

        assert store.get(s0.session_id) is not None  # 存活
        assert store.get(s3.session_id) is not None
        assert len(store._sessions) == 3

    def test_zero_length_text_allowed(self):
        store = ReadSessionStore()
        sess = store.create(domain="dom_read", url="https://e.com/j", title="t", text="", chunk_size=100)
        chunk = store.read(sess.session_id)
        assert chunk["text"] == ""
        assert chunk["can_continue"] is False


class TestSingletonAndConcurrency:
    def test_singleton_roundtrip(self):
        reset_read_session_store()
        assert get_read_session_store() is get_read_session_store()
        reset_read_session_store()
        assert get_read_session_store() is not None

    def test_concurrent_reads_no_overlap(self):
        """并发续读：每个分片只被消费一次（RLock 保护游标推进）"""
        store = ReadSessionStore()
        text = "".join(str(i % 10) for i in range(2000))  # 2000 字符可辨识
        sess = store.create(domain="browser_read", url="https://e.com/k", title="t", text=text, chunk_size=100)

        results, lock = [], threading.Lock()

        def worker():
            while True:
                with lock:
                    pass
                chunk = store.read(sess.session_id)
                if chunk is None or not chunk["text"]:
                    return
                with lock:
                    results.append(chunk["text"])

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        joined = "".join(results)
        assert len(joined) == 2000
        assert joined == text  # 分片无重复无丢失、顺序可拼接
