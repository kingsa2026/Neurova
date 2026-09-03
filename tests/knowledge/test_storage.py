"""Tests for knowledge/storage.py - core scenarios."""
import pytest


class TestKnowledgeStorage:
    def test_init_with_storage_path(self, tmp_path):
        from neurova.knowledge.storage import KnowledgeStorage
        store = KnowledgeStorage(str(tmp_path / "kb"))
        assert store is not None

    def test_create_and_get_config(self, tmp_path):
        from neurova.knowledge.storage import KnowledgeStorage
        store = KnowledgeStorage(str(tmp_path / "kb"))
        cid = store.create_config(user_id="u1", name="c1", source_type="web")
        assert isinstance(cid, str) and cid
        cfg = store.get_config_by_id(cid)
        assert cfg is not None
        assert cfg.get("user_id") == "u1"
        assert cfg.get("name") == "c1"

    def test_get_configs_by_user(self, tmp_path):
        from neurova.knowledge.storage import KnowledgeStorage
        store = KnowledgeStorage(str(tmp_path / "kb"))
        store.create_config(user_id="u1", name="a", source_type="web")
        store.create_config(user_id="u1", name="b", source_type="api")
        store.create_config(user_id="u2", name="c", source_type="web")
        result = store.get_configs_by_user("u1")
        assert isinstance(result, list)
        assert len(result) == 2

    def test_default_and_active_configs(self, tmp_path):
        from neurova.knowledge.storage import KnowledgeStorage
        store = KnowledgeStorage(str(tmp_path / "kb"))
        cid = store.create_config(user_id="u1", name="d", source_type="web", is_default=True, is_active=True)
        default = store.get_default_config("u1")
        active = store.get_active_config("u1")
        assert default is not None and default.get("id") == cid
        assert active is not None and active.get("id") == cid

    def test_update_and_delete_config(self, tmp_path):
        from neurova.knowledge.storage import KnowledgeStorage
        store = KnowledgeStorage(str(tmp_path / "kb"))
        cid = store.create_config(user_id="u1", name="orig", source_type="web")
        ok = store.update_config(cid, name="renamed")
        assert ok is True or ok is None
        assert store.get_config_by_id(cid).get("name") == "renamed"
        assert store.delete_config(cid) is True
        assert store.get_config_by_id(cid) is None

    def test_api_key_hash_and_verify(self, tmp_path):
        from neurova.knowledge.storage import KnowledgeStorage
        store = KnowledgeStorage(str(tmp_path / "kb"))
        key = "sk-test-1234567890"
        hashed = store._hash_api_key(key)
        assert isinstance(hashed, str) and len(hashed) > 0
        assert store.verify_api_key(key, hashed) is True
        assert store.verify_api_key("wrong-key", hashed) is False

    def test_persistence_across_instances(self, tmp_path):
        from neurova.knowledge.storage import KnowledgeStorage
        d = str(tmp_path / "kb")
        a = KnowledgeStorage(d)
        a.create_config(user_id="u1", name="persist", source_type="web")
        b = KnowledgeStorage(d)
        result = b.get_configs_by_user("u1")
        assert len(result) == 1
        assert result[0].get("name") == "persist"


class TestGetKnowledgeStorage:
    def test_returns_singleton(self):
        from neurova.knowledge.storage import get_knowledge_storage
        a = get_knowledge_storage()
        b = get_knowledge_storage()
        assert a is b
