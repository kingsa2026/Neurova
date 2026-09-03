"""Tests for cognitive_layers/memory_layer/storage.py — core scenario coverage.

Self-contained JSON-backed memory store with thread-safe RLock, dataclass
records, query/list/batch helpers, persistence and singleton factory.
"""
import json
import pytest


def _make_storage(tmp_path, monkeypatch=None):
    """Build a fresh MemoryStorage bound to a per-test directory."""
    from neurova.cognitive_layers.memory_layer import storage as mod
    target = tmp_path / "memory_store"
    target.mkdir(parents=True, exist_ok=True)
    return mod.MemoryStorage(str(target))


def _reset_memory_singleton(monkeypatch):
    from neurova.cognitive_layers.memory_layer import storage as mod
    monkeypatch.setattr(mod, "_singleton", None)


class TestMemoryStorageInit:
    def test_init_creates_empty_storage(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        storage = _make_storage(tmp_path)
        assert storage is not None
        assert storage.count() == 0
        stats = storage.get_stats()
        assert isinstance(stats, dict)
        assert stats["total"] == 0

    def test_init_loads_existing_records(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        target = tmp_path / "memory_store"
        target.mkdir(parents=True, exist_ok=True)
        first = MemoryStorage(str(target))
        mid = first.save(content="hello", memory_type="episodic", owner="agent_1")
        assert isinstance(mid, str) and mid
        second = MemoryStorage(str(target))
        assert second.count() == 1
        rec = second.get(mid)
        assert rec is not None
        assert rec["content"] == "hello"
        assert rec["memory_type"] == "episodic"


class TestMemoryRecordCrud:
    def test_save_returns_id_and_get_returns_record(self, tmp_path):
        storage = _make_storage(tmp_path)
        mid = storage.save(
            content="learned python",
            memory_type="semantic",
            owner="agent_1",
            tags=["programming", "python"],
            metadata={"source": "test"},
        )
        assert isinstance(mid, str) and mid.startswith("mem_")
        rec = storage.get(mid)
        assert rec is not None
        assert rec["id"] == mid
        assert rec["content"] == "learned python"
        assert rec["memory_type"] == "semantic"
        assert rec["owner"] == "agent_1"
        assert rec["tags"] == ["programming", "python"]
        assert rec["metadata"] == {"source": "test"}
        assert rec["access_count"] == 0
        assert isinstance(rec["created_at"], str) and rec["created_at"]
        assert isinstance(rec["updated_at"], str) and rec["updated_at"]

    def test_get_missing_returns_none(self, tmp_path):
        storage = _make_storage(tmp_path)
        assert storage.get("mem_does_not_exist") is None

    def test_delete_returns_true_and_removes(self, tmp_path):
        storage = _make_storage(tmp_path)
        mid = storage.save(content="x", memory_type="episodic", owner="a")
        assert storage.delete(mid) is True
        assert storage.get(mid) is None
        assert storage.delete(mid) is False
        assert storage.delete("mem_nope") is False

    def test_update_memory_merges_fields(self, tmp_path):
        storage = _make_storage(tmp_path)
        mid = storage.save(content="orig", memory_type="episodic", owner="a")
        original_updated = storage.get(mid)["updated_at"]
        ok = storage.update_memory(mid, content="new", importance=0.9)
        assert ok is True
        rec = storage.get(mid)
        assert rec["content"] == "new"
        assert rec["importance"] == 0.9
        assert rec["updated_at"] >= original_updated

    def test_update_missing_returns_false(self, tmp_path):
        storage = _make_storage(tmp_path)
        assert storage.update_memory("mem_nope", content="x") is False

    def test_increment_access_increments_counter(self, tmp_path):
        storage = _make_storage(tmp_path)
        mid = storage.save(content="x", memory_type="episodic", owner="a")
        assert storage.get(mid)["access_count"] == 0
        assert storage.increment_access(mid) is True
        assert storage.get(mid)["access_count"] == 1
        storage.increment_access(mid)
        assert storage.get(mid)["access_count"] == 2
        assert storage.increment_access("mem_nope") is False


class TestMemoryStorageQueries:
    def _seed(self, storage):
        ids = []
        ids.append(storage.save(content="a", memory_type="episodic", owner="agent_1", tags=["work", "urgent"]))
        ids.append(storage.save(content="b", memory_type="semantic", owner="agent_1", tags=["work"]))
        ids.append(storage.save(content="c", memory_type="episodic", owner="agent_2", tags=["personal"]))
        ids.append(storage.save(content="d", memory_type="procedural", owner="agent_2", tags=[]))
        return ids

    def test_count_reflects_saves_and_deletes(self, tmp_path):
        storage = _make_storage(tmp_path)
        assert storage.count() == 0
        ids = self._seed(storage)
        assert storage.count() == 4
        storage.delete(ids[0])
        assert storage.count() == 3

    def test_query_by_type(self, tmp_path):
        storage = _make_storage(tmp_path)
        self._seed(storage)
        episodic = storage.query(memory_type="episodic")
        assert isinstance(episodic, list)
        assert len(episodic) == 2
        assert all(r["memory_type"] == "episodic" for r in episodic)

    def test_query_by_owner(self, tmp_path):
        storage = _make_storage(tmp_path)
        self._seed(storage)
        agent_2 = storage.query(owner="agent_2")
        assert len(agent_2) == 2
        assert all(r["owner"] == "agent_2" for r in agent_2)

    def test_query_by_time_range(self, tmp_path):
        storage = _make_storage(tmp_path)
        self._seed(storage)
        all_records = storage.query()
        assert len(all_records) == 4
        from datetime import datetime, timezone, timedelta
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        future_records = storage.query(end_time=future)
        assert len(future_records) == 4
        past_records = storage.query(start_time="2000-01-01T00:00:00+00:00", end_time="2000-01-02T00:00:00+00:00")
        assert past_records == []

    def test_list_by_tags(self, tmp_path):
        storage = _make_storage(tmp_path)
        self._seed(storage)
        work = storage.list_by_tags(["work"])
        assert isinstance(work, list)
        assert len(work) == 2
        urgent = storage.list_by_tags(["urgent"])
        assert len(urgent) == 1
        assert urgent[0]["content"] == "a"


class TestMemoryStorageBatch:
    def test_batch_save_creates_all_records(self, tmp_path):
        storage = _make_storage(tmp_path)
        payloads = [
            {"content": f"mem-{i}", "memory_type": "episodic", "owner": "a", "tags": [f"t{i}"]}
            for i in range(5)
        ]
        ids = storage.batch_save(payloads)
        assert isinstance(ids, list)
        assert len(ids) == 5
        assert all(isinstance(i, str) and i.startswith("mem_") for i in ids)
        assert storage.count() == 5

    def test_batch_delete_removes_listed(self, tmp_path):
        storage = _make_storage(tmp_path)
        ids = storage.batch_save([
            {"content": "x", "memory_type": "episodic", "owner": "a"},
            {"content": "y", "memory_type": "episodic", "owner": "a"},
            {"content": "z", "memory_type": "episodic", "owner": "a"},
        ])
        removed = storage.batch_delete([ids[0], ids[2], "mem_nope"])
        assert removed == 2
        assert storage.count() == 1


class TestPersistence:
    def test_persistence_across_instances(self, tmp_path):
        target = str(tmp_path / "persist")
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        first = MemoryStorage(target)
        ids = first.batch_save([
            {"content": "p1", "memory_type": "episodic", "owner": "a", "tags": ["t"]},
            {"content": "p2", "memory_type": "semantic", "owner": "a", "tags": []},
        ])
        first.update_memory(ids[0], content="p1-updated")
        first.increment_access(ids[1])

        second = MemoryStorage(target)
        assert second.count() == 2
        rec0 = second.get(ids[0])
        assert rec0["content"] == "p1-updated"
        rec1 = second.get(ids[1])
        assert rec1["access_count"] == 1

    def test_storage_file_is_valid_json(self, tmp_path):
        target = tmp_path / "json_check"
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        storage = MemoryStorage(str(target))
        storage.save(content="hello", memory_type="episodic", owner="a")
        json_files = list(target.glob("*.json"))
        assert len(json_files) >= 1
        data = json.loads(json_files[0].read_text(encoding="utf-8"))
        assert isinstance(data, dict)


class TestGetMemoryStorageSingleton:
    def test_factory_returns_singleton(self, tmp_path, monkeypatch):
        from neurova.cognitive_layers.memory_layer import storage as mod
        monkeypatch.setattr(mod, "_DEFAULT_DIR", str(tmp_path / "singleton"))
        _reset_memory_singleton(monkeypatch)
        try:
            a = mod.get_memory_storage()
            b = mod.get_memory_storage()
            assert a is b
        finally:
            _reset_memory_singleton(monkeypatch)
