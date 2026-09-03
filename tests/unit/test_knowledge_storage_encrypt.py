"""
测试：KnowledgeStorage API Key 加密存储 + 配置引用解码（A+B）

背景：
  storage 现有 _hash_api_key 为单向 SHA-256，B 阶段（画布 kb_config_id
  引用配置）需要从配置中取出原始 API Key，必须可逆加密。

契约：
  1. create_config 存入 api_key_encrypted（加密）；api_key_hash 仍保留（校验用）
  2. decrypt_api_key(config_id) 返回原始 key（Fernet 解密）
  3. 未加密/密钥缺失 → 返回 None（不抛异常）
  4. hash 与 encrypt 不同：明文不回显、hash 不可逆
"""

import pytest

from neurova.knowledge.storage import KnowledgeStorage


@pytest.fixture
def storage(tmp_path, monkeypatch):
    # 固定 Fernet 密钥，使加密结果可跨实例验证
    from cryptography.fernet import Fernet

    monkeypatch.setenv("NEUROVA_KB_SECRET", Fernet.generate_key().decode())
    return KnowledgeStorage(str(tmp_path / "kb"))


class TestEncryptedApiKey:
    def test_create_config_stores_encrypted(self, storage):
        cid = storage.create_config(
            user_id="u-1", name="my kb", source_type="iflow", api_key="sk-secret-abc"
        )
        cfg = storage.get_config_by_id(cid)
        # 加密字段存在且非明文
        assert cfg["api_key_encrypted"]
        assert cfg["api_key_hash"]
        assert "sk-secret-abc" not in str(cfg["api_key_encrypted"])

    def test_decrypt_api_key_roundtrip(self, storage):
        cid = storage.create_config(
            user_id="u-1", name="my kb", source_type="iflow", api_key="sk-life"
        )
        assert storage.decrypt_api_key(cid) == "sk-life"

    def test_decrypt_missing_returns_none(self, storage):
        assert storage.decrypt_api_key("no-such-id") is None

    def test_decrypt_unencrypted_returns_none(self, storage):
        cid = storage.create_config(
            user_id="u-1", name="legacy", source_type="iflow", api_key=None
        )
        cfg = storage.get_config_by_id(cid)
        assert cfg.get("api_key_encrypted") is None
        assert storage.decrypt_api_key(cid) is None

    def test_update_config_reencrypts(self, storage):
        cid = storage.create_config(
            user_id="u-1", name="my kb", source_type="iflow", api_key="old-key"
        )
        storage.update_config(cid, api_key="new-key")
        assert storage.decrypt_api_key(cid) == "new-key"
