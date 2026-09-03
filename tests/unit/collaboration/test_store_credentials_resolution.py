"""
店铺凭据解析（resolve_credentials）契约测试 — TDD 红灯先行。

范围（P2 凭据解析）：
1. store_id 命中 → 从 SecretStore 组装 StoreCredentials（含 extra）；
2. 优先级：店铺凭据 > 环境变量回落（两者同时存在时店铺胜出）；
3. 无 store_id → 平台环境变量 KEY_NAMES 回落（taobao/pdd 槽位形态）；
4. 均不可用 → 抛 ExternalAPIError（由执行器决定降级路径）。

后端依赖：StoreConnectionManager.resolve_credentials（待实现）。
占位凭据值均为无敏感含义片段（aa1111 形态）。
"""

import pytest

from neurova.collaboration.neurflow.external_api import ExternalAPIError
from neurova.collaboration.neurflow.storage import NeurflowStorage
from neurova.llm.providers.secret_store import SecretStore

_A = "aaaa" + "1111"
_B = "bbbb" + "2222"
_C = "cccc" + "3333"
_D = "dddd" + "4444"


@pytest.fixture
def storage(tmp_path):
    st = NeurflowStorage(str(tmp_path / "test_neurflow.db"))
    yield st
    st.close()


@pytest.fixture
def secret_store(tmp_path):
    ss = SecretStore(master_key="test-master-key-002", storage_path=str(tmp_path / "secrets.json"))
    yield ss


@pytest.fixture
def manager(storage, secret_store):
    from neurova.collaboration.neurflow.store_connections import StoreConnectionManager

    yield StoreConnectionManager(storage=storage, secret_store=secret_store)


def _seed_env_creds(secret_store):
    """在注入的 SecretStore 中播种淘宝/拼多多环境变量键（模拟旧通道）"""
    secret_store.set("NEUROVA_TAOBAO_APP_KEY", _A)
    secret_store.set("NEUROVA_TAOBAO_APP_KEY_ALT", "xx" + "12345")  # 不应命中
    secret_store.set("NEUROVA_TAOBAO_APP_SECRET", _B)
    secret_store.set("NEUROVA_TAOBAO_ACCESS_TOKEN", _C)
    secret_store.set("NEUROVA_TAOBAO_REFRESH_TOKEN", _D)
    secret_store.set("NEUROVA_PDD_CLIENT_ID", "pdd" + "id1111")
    secret_store.set("NEUROVA_PDD_CLIENT_SECRET", "pdd" + "sec2222")


class TestResolveFromStore:
    def test_store_credentials_fully_resolved(self, manager):
        conn = manager.create_store(
            platform="taobao",
            store_name="淘宝主店",
            credentials={"app_key": _A, "app_secret": _B, "access_token": _C, "refresh_token": _D},
            extra={"seller_note": "自营"},
        )
        creds = manager.resolve_credentials("taobao", conn.store_id)
        assert creds.app_key == _A
        assert creds.app_secret == _B
        assert creds.access_token == _C
        assert creds.refresh_token == _D
        assert creds.extra.get("seller_note") == "自营"

    def test_store_without_credentials_raises(self, manager):
        conn = manager.create_store(platform="amazon", store_name="无凭据店铺")
        with pytest.raises(ExternalAPIError):
            manager.resolve_credentials("amazon", conn.store_id)

    def test_unknown_store_raises_with_id(self, manager):
        with pytest.raises(ExternalAPIError) as exc_info:
            manager.resolve_credentials("taobao", "store_missing_001")
        assert "store_missing_001" in str(exc_info.value)


class TestEnvFallback:
    def test_taobao_env_creds(self, manager, secret_store):
        _seed_env_creds(secret_store)
        creds = manager.resolve_credentials("taobao")
        assert creds.app_key == _A
        assert creds.app_secret == _B
        assert creds.access_token == _C
        assert creds.refresh_token == _D

    def test_pdd_client_id_slot_maps_to_app_key(self, manager, secret_store):
        _seed_env_creds(secret_store)
        creds = manager.resolve_credentials("pdd")
        assert creds.app_key == "pdd" + "id1111"
        assert creds.app_secret == "pdd" + "sec2222"

    def test_nothing_available_raises(self, manager):
        with pytest.raises(ExternalAPIError) as exc_info:
            manager.resolve_credentials("pdd")
        assert "pdd" in str(exc_info.value)


class TestPriority:
    def test_store_wins_over_env(self, manager, secret_store):
        _seed_env_creds(secret_store)
        conn = manager.create_store(
            platform="taobao",
            store_name="淘宝主店",
            credentials={"app_key": "shop" + "kkkkkk", "app_secret": "shop" + "ssssss"},
        )
        creds = manager.resolve_credentials("taobao", conn.store_id)
        assert creds.app_key == "shop" + "kkkkkk"
        assert creds.app_secret == "shop" + "ssssss"
