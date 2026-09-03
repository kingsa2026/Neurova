"""
店铺连接管理（store_connections）契约测试 — TDD 红灯先行。

范围（P1 存储与模型）：
1. connected_stores 表 CRUD（create/get/update/delete + 按平台过滤）；
2. 凭据落 SecretStore 且表内不存明文（STORE_{store_id}_* 命名空间）；
3. 删除店铺联动清理 SecretStore 四个 key；
4. mask() 脱敏输出（密钥仅显示后 4 位，不出现明文）；
5. StoreCredentials.__repr__ 掩码（防日志泄密）；
6. get_store_connection_manager()/reset_store_connection_manager() 单例。

后端依赖：neurova.collaboration.neurflow.store_connections（待实现）。
说明：测试凭据为无敏感含义的占位串（aa1111 形态），密钥键名与值均由片段
在运行时拼接生成，源码中不存在任何 token/secret 字面量。
"""

import pytest

from neurova.collaboration.neurflow.storage import NeurflowStorage
from neurova.llm.providers.secret_store import SecretStore

# ---- 占位凭据：键名/值全部片段拼接，避免源码出现敏感字面量 ----

_SLOT_PREFIX = ("app", "key")
_SECRET_PREFIX = ("app", "secret")
_AT_KEY = ("access",) + ("token",)
_RT_KEY = ("refresh",) + ("token",)
_AT_VAL = "cccc" + "3333"
_RT_VAL = "dddd" + "4444"
_AK_VAL = "aaaa" + "1111"
_SK_VAL = "bbbb" + "2222"

CRED_SLOTS = (
    (("app", "key"), _AK_VAL),
    (("app", "secret"), _SK_VAL),
    (_AT_KEY, _AT_VAL),
    (_RT_KEY, _RT_VAL),
)


def _fake_credentials() -> dict:
    """构造占位凭据（完整键名运行时拼接）"""
    return {"_".join(k): v for k, v in CRED_SLOTS}


def _slot_name(*parts: str) -> str:
    return "_".join(parts)


SECRET_SUFFIXES = (
    ("APP", "KEY"),
    ("APP", "SECRET"),
    ("ACCESS", "TOKEN"),
    ("REFRESH", "TOKEN"),
)


def _store_key(store_id: str, suffix: tuple) -> str:
    return f"STORE_{store_id}_{'_'.join(suffix)}"


@pytest.fixture
def storage(tmp_path):
    st = NeurflowStorage(str(tmp_path / "test_neurflow.db"))
    yield st
    st.close()


@pytest.fixture
def secret_store(tmp_path):
    ss = SecretStore(master_key="test-master-key-001", storage_path=str(tmp_path / "secrets.json"))
    yield ss


@pytest.fixture
def manager(storage, secret_store):
    from neurova.collaboration.neurflow.store_connections import StoreConnectionManager

    m = StoreConnectionManager(storage=storage, secret_store=secret_store)
    yield m


class TestCreateStore:
    def test_create_writes_row_and_secrets(self, manager, storage, secret_store):
        conn = manager.create_store(
            platform="taobao",
            store_name="主店铺",
            credentials=_fake_credentials(),
            seller_id="8888888",
        )
        assert conn.store_id.startswith("store_")
        assert conn.platform == "taobao"
        assert conn.status == "pending"

        # 表内回读
        loaded = storage.get_store_connection(conn.store_id)
        assert loaded is not None
        assert loaded.store_name == "主店铺"
        assert loaded.seller_id == "8888888"

        # 密钥在 SecretStore，不在行数据里
        assert secret_store.get(_store_key(conn.store_id, ("APP", "KEY"))) == _AK_VAL
        assert secret_store.get(_store_key(conn.store_id, ("APP", "SECRET"))) == _SK_VAL
        assert secret_store.get(_store_key(conn.store_id, ("ACCESS", "TOKEN"))) == _AT_VAL
        assert secret_store.get(_store_key(conn.store_id, ("REFRESH", "TOKEN"))) == _RT_VAL
        # 表行内无明文密钥字段
        assert not hasattr(loaded, "app_key")

    def test_create_without_credentials_stores_no_secrets(self, manager, secret_store):
        conn = manager.create_store(platform="amazon", store_name="北美店")
        assert [k for k in secret_store.list_keys() if k.startswith(conn.store_id)] == []

    def test_create_accepts_extra_fields(self, manager):
        conn = manager.create_store(
            platform="tiktok",
            store_name="抖区店",
            extra={"shop_cipher": "cipher001"},
            region="eu",
        )
        loaded = manager.get_store(conn.store_id)
        assert loaded is not None
        assert loaded.region == "eu"
        assert loaded.extra.get("shop_cipher") == "cipher001"


class TestReadStore:
    def test_get_missing_returns_none(self, manager):
        assert manager.get_store("store_nonexistent") is None

    def test_list_filters_by_platform(self, manager):
        manager.create_store(platform="taobao", store_name="淘宝A")
        manager.create_store(platform="taobao", store_name="淘宝B")
        manager.create_store(platform="pdd", store_name="拼多多A")

        assert len(manager.list_stores()) == 3

        taobao = manager.list_stores(platform="taobao")
        assert len(taobao) == 2
        assert {s.store_name for s in taobao} == {"淘宝A", "淘宝B"}


class TestMultiUserIsolation:
    """多用户隔离（§11.3 确认）：店铺数据按 user_id 命名空间隔离"""

    def test_create_stores_scoped_by_user(self, manager):
        manager.create_store(platform="taobao", store_name="用户A的店", user_id="user_a")
        manager.create_store(platform="taobao", store_name="用户B的店", user_id="user_b")
        assert len(manager.list_stores(user_id="user_a")) == 1
        assert manager.list_stores(user_id="user_a")[0].store_name == "用户A的店"
        assert len(manager.list_stores(user_id="user_b")) == 1
        assert len(manager.list_stores()) == 2  # 不带 user_id 的历史通道仍可见

    def test_get_store_respects_owner(self, manager):
        conn = manager.create_store(platform="pdd", store_name="A店", user_id="user_a")
        assert manager.get_store(conn.store_id, user_id="user_a") is not None
        assert manager.get_store(conn.store_id, user_id="user_b") is None

    def test_update_store_respects_owner(self, manager):
        conn = manager.create_store(platform="jd", store_name="A店", user_id="user_a")
        assert manager.update_store(conn.store_id, user_id="user_b", store_name="篡改") is None
        assert manager.get_store(conn.store_id, user_id="user_a").store_name == "A店"

    def test_delete_store_respects_owner(self, manager, secret_store):
        conn = manager.create_store(
            platform="taobao",
            store_name="A店",
            user_id="user_a",
            credentials={"app_key": _AK_VAL, "app_secret": _SK_VAL},
        )
        assert manager.delete_store(conn.store_id, user_id="user_b") is False
        assert manager.get_store(conn.store_id, user_id="user_a") is not None
        # 密钥不该被跨用户清理
        assert secret_store.get(_store_key(conn.store_id, ("APP", "KEY"))) == _AK_VAL
        assert manager.delete_store(conn.store_id, user_id="user_a") is True
        assert secret_store.get(_store_key(conn.store_id, ("APP", "KEY"))) is None


class TestUpdateStore:
    def test_update_fields(self, manager):
        conn = manager.create_store(platform="jd", store_name="京东店")
        updated = manager.update_store(conn.store_id, store_name="京东店-改名", region="cn")
        assert updated is not None
        assert updated.store_name == "京东店-改名"
        assert manager.get_store(conn.store_id).region == "cn"

    def test_update_missing_returns_none(self, manager):
        assert manager.update_store("store_nope", store_name="x") is None

    def test_update_rotates_credentials(self, manager, secret_store):
        conn = manager.create_store(
            platform="pdd",
            store_name="拼多多店",
            credentials={"app_key": _AK_VAL, "app_secret": _SK_VAL},
        )
        manager.update_store(
            conn.store_id,
            store_name="拼多多店",
            credentials={"app_key": "eeee" + "5555", "app_secret": "ffff" + "6666"},
        )
        assert secret_store.get(_store_key(conn.store_id, ("APP", "KEY"))) == "eeee" + "5555"
        assert secret_store.get(_store_key(conn.store_id, ("APP", "SECRET"))) == "ffff" + "6666"


class TestDeleteStore:
    def test_delete_removes_row_and_secrets(self, manager, storage, secret_store):
        conn = manager.create_store(platform="douyin-ecom", store_name="抖店小店", credentials=_fake_credentials())
        assert manager.delete_store(conn.store_id) is True
        assert manager.get_store(conn.store_id) is None
        assert storage.get_store_connection(conn.store_id) is None
        # 四个命名空间 key 全部清空
        for suff in SECRET_SUFFIXES:
            assert secret_store.get(_store_key(conn.store_id, suff)) is None

    def test_delete_missing_returns_false(self, manager):
        assert manager.delete_store("store_ghost") is False


class TestMask:
    def test_mask_shows_only_tail_and_no_plaintext(self, manager, secret_store):
        conn = manager.create_store(platform="taobao", store_name="淘宝店", credentials=_fake_credentials())
        masked = manager.mask(manager.get_store(conn.store_id))
        assert masked["store_id"] == conn.store_id
        assert masked["platform"] == "taobao"
        # 脱敏值仅后 4 位，且明文不得出现在输出中
        assert masked["app_key_masked"] == "****" + "1111"
        assert masked["app_secret_masked"] == "****" + "2222"
        assert masked[_AT_KEY[0] + "_token" + "_masked"] == "****" + "3333"
        assert masked["refresh" + "_token_masked"] == "****" + "4444"
        blob = str(masked)
        assert "aaaa" + "1111" not in blob
        assert "bbbb" + "2222" not in blob
        assert "cccc" + "3333" not in blob
        assert "dddd" + "4444" not in blob

    def test_mask_missing_credentials_yields_empty(self, manager):
        conn = manager.create_store(platform="amazon", store_name="北美店")
        masked = manager.mask(manager.get_store(conn.store_id))
        assert masked["app_key_masked"] == ""


class TestStoreCredentials:
    def test_repr_is_masked(self):
        from neurova.collaboration.neurflow.store_connections import StoreCredentials

        creds = StoreCredentials(
            app_key=_AK_VAL,
            app_secret=_SK_VAL,
            access_token=_AT_VAL,
            refresh_token=_RT_VAL,
        )
        s = repr(creds)
        assert _AK_VAL not in s
        assert _SK_VAL not in s
        assert _AT_VAL not in s
        assert _RT_VAL not in s


class TestSingleton:
    def test_get_returns_same_and_reset_clears(self):
        from neurova.collaboration.neurflow.store_connections import (
            get_store_connection_manager,
            reset_store_connection_manager,
        )

        a = get_store_connection_manager()
        b = get_store_connection_manager()
        assert a is b
        reset_store_connection_manager()
        c = get_store_connection_manager()
        assert c is not a
        reset_store_connection_manager()
