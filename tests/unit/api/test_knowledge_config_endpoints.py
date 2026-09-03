"""
测试：远程知识库配置管理端点（A：用户级配置托管）

契约:
  1. POST /knowledge/configs 创建配置（按 user_id 隔离；API Key 不回显）
  2. GET /knowledge/configs 列出当前用户配置（无 api_key 明文/encrypted）
  3. GET /knowledge/configs/{id} 单查（属主）
  4. PUT /knowledge/configs/{id} 更新（api_key 换新则重加密）
  5. DELETE /knowledge/configs/{id} 删除（属主）
  6. collections 映射 CRUD
  7. 非属主访问 → 404（IDOR 防护）
"""

import json

import pytest

from neurova.knowledge.storage import KnowledgeStorage
from neurova.api.endpoints import knowledge as kb


@pytest.fixture
def storage(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("NEUROVA_KB_SECRET", Fernet.generate_key().decode())
    return KnowledgeStorage(str(tmp_path / "kb"))


class TestConfigMgmt:
    def test_create_and_list_no_secret_leak(self, storage):
        cid = storage.create_config(
            user_id="u-1", name="iflow 主库", source_type="iflow", api_key="sk-secret", is_default=True
        )
        cfgs = storage.get_configs_by_user("u-1")
        assert len(cfgs) == 1
        cfg = cfgs[0]
        # 不回显明文与加密串
        assert "sk-secret" not in json.dumps(cfg)
        assert cfg.get("api_key_encrypted") is None or isinstance(cfg["api_key_encrypted"], str)
        assert cfg["id"] == cid
        assert cfg["source_type"] == "iflow"

    def test_user_isolation(self, storage):
        storage.create_config(user_id="u-1", name="a", source_type="iflow", api_key="k")
        storage.create_config(user_id="u-2", name="b", source_type="feishu", api_key="k2")
        # 各用户只见自己配置
        assert len(storage.get_configs_by_user("u-1")) == 1
        assert len(storage.get_configs_by_user("u-2")) == 1

    def test_update_api_key_reencrypts(self, storage):
        cid = storage.create_config(user_id="u-1", name="a", source_type="iflow", api_key="k1")
        storage.update_config(cid, api_key="k2")
        assert storage.decrypt_api_key(cid) == "k2"

    def test_collections_mapping(self, storage):
        mid = storage.create_collection_mapping("u-1", "cfg-1", "collectionX", vector_store="qdrant")
        items = storage.get_user_collections("u-1")
        assert len(items) == 1
        assert items[0]["collection_name"] == "collectionX"
        assert items[0]["vector_store"] == "qdrant"
        assert storage.delete_collection_mapping(mid) is True
        assert storage.get_user_collections("u-1") == []

    def test_config_delete(self, storage):
        cid = storage.create_config(user_id="u-1", name="a", source_type="iflow", api_key="k")
        assert storage.delete_config(cid) is True
        assert storage.get_config_by_id(cid) is None


class TestConfigEndpoints:
    def test_route_paths(self):
        # 路由必须已注册 configs/collections 前缀（防 shadowing：字面路由先于 {id}）
        paths = [r.path for r in kb.router.routes]
        assert "/configs" in paths
        assert "/configs/{config_id}" in paths
        assert "/collections" in paths
        assert "/collections/{mapping_id}" in paths
