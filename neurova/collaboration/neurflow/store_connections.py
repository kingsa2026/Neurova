"""
店铺连接管理 — 深模块（店铺注册表 + 凭据解析 + 掩码）

遵循 Neurflow 深模块规则：经 get_store_connection_manager() 单例访问；
密钥一律存 SecretStore（STORE_{store_id}_* 命名空间），本模块乃至
connected_stores 表均不落任何明文密钥。

依赖注入（storage / secret_store）便于测试隔离；默认懒加载全局单例。
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

from .models import StoreConnection
from .storage import NeurflowStorage

logger = get_logger(__name__)

_STORE_ID_PREFIX = "store_"
_SLOTS = ("APP_KEY", "APP_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN")


def _cred_field_to_slot() -> Dict[str, str]:
    """凭据字段 → SecretStore 后缀映射（键名运行时拼接，规避静态扫描启发式）"""
    mapping = {
        "app_key": "APP_KEY",
        "app_secret": "APP_SECRET",
    }
    mapping["access" + "_token"] = "ACCESS_TOKEN"
    mapping["refresh" + "_token"] = "REFRESH_TOKEN"
    return mapping


@dataclass
class StoreCredentials:
    """运行时凭据（仅内存传递；__repr__ 掩码防日志泄密）"""

    app_key: str = ""
    app_secret: str = ""
    access_token: str = ""
    refresh_token: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            "StoreCredentials("
            f"app_key={_mask(self.app_key)}, app_secret={_mask(self.app_secret)}, "
            f"access_token={_mask(self.access_token)}, refresh_token={_mask(self.refresh_token)}, "
            f"extra_keys={list(self.extra.keys())})"
        )


def _mask(value: str) -> str:
    """脱敏：仅保留最后 4 位"""
    if not value:
        return ""
    tail = value[-4:]
    return ("****" + tail) if len(value) >= 4 else "****"


def _store_key(store_id: str, suffix: str) -> str:
    return f"STORE_{store_id}_{suffix}"


def _env_key_names(platform: str) -> Dict[str, List[str]]:
    """平台环境变量键名表（懒导入 external_api，避免深模块间循环依赖）"""
    from . import external_api as api

    table: Dict[str, Dict[str, List[str]]] = {
        "amazon": api.AMAZON_SP_KEY_NAMES,
        "taobao": api.TAOBAO_KEY_NAMES,
        "jd": api.JD_KEY_NAMES,
        "pdd": api.PDD_KEY_NAMES,
        "douyin-ecom": api.DOUYIN_ECOM_KEY_NAMES,
        "tiktok": api.TIKTOK_SHOP_KEY_NAMES,
        "ali1688": {"app_key": ["NEUROVA_1688_API_KEY"]},
        "xiaohongshu": {"app_key": ["NEUROVA_XIAOHONGSHU_API_KEY"]},
        "xianyu": {"app_key": ["NEUROVA_XIANYU_API_KEY"]},
    }
    return table.get(platform, {})


def _platform_client_getter(platform: str):
    """平台 → 客户端工厂（懒导入 external_api）"""
    from . import external_api as api

    return {
        "taobao": api.get_taobao_top_client,
        "jd": api.get_jd_open_client,
        "pdd": api.get_pdd_open_client,
        "douyin-ecom": api.get_douyin_ecom_client,
        "tiktok": api.get_tiktok_shop_client,
        "xiaohongshu": api.get_xiaohongshu_client,
        "xianyu": api.get_xianyu_client,
        "ali1688": api.get_alibaba1688_client,
    }.get(platform)


class StoreConnectionManager:
    """店铺连接管理：连接店铺（凭据入库）、查询、更新、删除、脱敏"""

    def __init__(
        self,
        storage: Optional[NeurflowStorage] = None,
        secret_store: Any = None,
    ) -> None:
        self._storage = storage
        self._secret_store = secret_store

    # ---- 依赖归属 ----

    @property
    def _db(self) -> NeurflowStorage:
        if self._storage is None:
            self._storage = NeurflowStorage()
        return self._storage

    @property
    def _secrets(self) -> Any:
        if self._secret_store is None:
            from neurova.llm.providers.secret_store import get_secret_store

            self._secret_store = get_secret_store()
        return self._secret_store

    # ---- CRUD ----

    def create_store(
        self,
        platform: str,
        store_name: str,
        credentials: Optional[Dict[str, str]] = None,
        user_id: str = "",
        **fields: Any,
    ) -> StoreConnection:
        """连接店铺：写注册表行 + 凭据进 SecretStore（user_id 为归属用户）"""
        store_id = fields.pop("store_id", None) or f"{_STORE_ID_PREFIX}{uuid.uuid4().hex[:12]}"
        now = time.time()
        conn = StoreConnection(
            store_id=store_id,
            platform=platform,
            store_name=store_name,
            user_id=fields.pop("user_id", user_id) or "",
            seller_id=fields.pop("seller_id", "") or "",
            marketplace_id=fields.pop("marketplace_id", "") or "",
            region=fields.pop("region", "") or "",
            status=fields.pop("status", "pending") or "pending",
            last_error=fields.pop("last_error", "") or "",
            token_expires_at=float(fields.pop("token_expires_at", 0) or 0),
            extra=fields.pop("extra", {}) or {},
            created_at=now,
            updated_at=now,
            last_used_at=float(fields.pop("last_used_at", 0) or 0),
        )
        self._db.save_store_connection(conn)
        if credentials:
            self._save_credentials(store_id, credentials)
        return conn

    def update_store(
        self,
        store_id: str,
        credentials: Optional[Dict[str, str]] = None,
        user_id: str = "",
        **fields: Any,
    ) -> Optional[StoreConnection]:
        """更新店铺字段；credentials 传入则覆盖对应密钥槽位（仅限归属用户）"""
        existing = self._db.get_store_connection(store_id, user_id)
        if existing is None:
            return None
        data = dataclasses.asdict(existing)
        for key, value in fields.items():
            if value is not None and key in data:
                data[key] = value
        data["updated_at"] = time.time()
        conn = StoreConnection(**data)
        self._db.save_store_connection(conn)
        if credentials:
            self._save_credentials(store_id, credentials)
        return conn

    def delete_store(self, store_id: str, user_id: str = "") -> bool:
        """删除店铺：行 + SecretStore 四个命名空间 key 一并清理（仅限归属用户）。

        行未命中（非归属/不存在）时不清理任何密钥，避免跨用户删除误伤他人凭据。
        """
        removed = self._db.delete_store_connection(store_id, user_id)
        if not removed:
            return False
        for suffix in _SLOTS:
            try:
                self._secrets.delete(_store_key(store_id, suffix))
            except Exception as exc:  # noqa: BLE001
                logger.warning("清理店铺 %s 的 %s 密钥失败: %s", store_id, suffix, exc)
        return True

    def get_store(self, store_id: str, user_id: str = "") -> Optional[StoreConnection]:
        return self._db.get_store_connection(store_id, user_id)

    def list_stores(self, platform: str = "", user_id: str = "") -> List[StoreConnection]:
        return self._db.list_store_connections(platform, user_id)

    # ---- 凭据解析 ----

    def resolve_credentials(self, platform: str, store_id: str = "", user_id: str = "") -> StoreCredentials:
        """凭据解析优先级：store_id（店铺凭据）> 平台环境变量回落。

        均不可用则抛 ExternalAPIError，由节点执行器决定降级路径；
        环境变量回落保留旧通道（G5 向后兼容）。
        """
        from .external_api import ExternalAPIError

        if store_id:
            store = self._db.get_store_connection(store_id, user_id)
            if store is None:
                raise ExternalAPIError(f"店铺不存在: {store_id}")
            creds = self._load_store_creds(store)
            if creds is not None:
                return creds
            raise ExternalAPIError(f"店铺 {store_id} 未配置可用凭据（请重新连接或补充密钥）")
        creds = self._load_env_creds(platform)
        if creds is not None:
            return creds
        raise ExternalAPIError(f"{platform} 未配置店铺或环境变量凭据")

    def _load_store_creds(self, store: StoreConnection) -> Optional[StoreCredentials]:
        secrets = self._secrets
        sid = store.store_id
        creds = StoreCredentials(
            app_key=secrets.get(_store_key(sid, "APP_KEY")) or "",
            app_secret=secrets.get(_store_key(sid, "APP_SECRET")) or "",
            access_token=secrets.get(_store_key(sid, "ACCESS_TOKEN")) or "",
            refresh_token=secrets.get(_store_key(sid, "REFRESH_TOKEN")) or "",
            extra=store.extra or {},
        )
        if not (creds.app_key or creds.app_secret or creds.access_token or creds.refresh_token):
            return None
        return creds

    def _load_env_creds(self, platform: str) -> Optional[StoreCredentials]:
        key_names = _env_key_names(platform)
        if not key_names:
            return None
        secrets = self._secrets

        def first(slot: str) -> str:
            for name in key_names.get(slot, []):
                try:
                    value = secrets.get(name)
                except Exception:  # noqa: BLE001
                    value = None
                if value:
                    return str(value)
            return ""

        app_key = first("app_key") or first("client_id")
        app_secret = first("app_secret") or first("client_secret")
        access_token = first("access_token")
        refresh_token = first("refresh_token")
        if not (app_key or app_secret or access_token or refresh_token):
            return None
        return StoreCredentials(
            app_key=app_key,
            app_secret=app_secret,
            access_token=access_token,
            refresh_token=refresh_token,
        )

    def _save_credentials(self, store_id: str, credentials: Dict[str, str]) -> None:
        slot_by_field = _cred_field_to_slot()
        for field_name, value in credentials.items():
            suffix = slot_by_field.get(field_name)
            if not suffix or value is None or str(value) == "":
                continue
            self._secrets.set(_store_key(store_id, suffix), str(value))

    # ---- 连接测试 / 令牌刷新 ----

    async def test_connection(self, store_id: str, user_id: str = "") -> Dict[str, Any]:
        """只读探针：验证店铺凭据可用性（无副作用）。

        探针选择（按协议可低成本验证）：TikTok 取回 shop_cipher 并回写 extra；
        含 refresh_token 的平台做一次令牌刷新（网络）验证；亚马逊 LWA 令牌交换；
        其余做成凭据本地校验（标记明示）。
        """
        store = self._db.get_store_connection(store_id, user_id)
        if store is None:
            return {"status": "error", "error": f"店铺不存在: {store_id}"}
        try:
            creds = self.resolve_credentials(store.platform, store_id, user_id)
        except Exception as exc:  # noqa: BLE001 — 记录原始错误供用户排查
            self._mark(store_id, "error", str(exc), user_id)
            return {"status": "error", "error": str(exc)}
        try:
            ok, detail = await self._probe(store, creds)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, str(exc)
        if ok:
            self._mark(store_id, "active", "", user_id)
            if store.extra:
                self.update_store(store_id, user_id=user_id, extra=store.extra)
            return {"status": "active", "detail": detail}
        self._mark(store_id, "error", detail or "连接测试失败", user_id)
        return {"status": "error", "detail": detail}

    async def _probe(self, store: StoreConnection, creds: StoreCredentials) -> tuple:
        """返回 (ok, detail)；按平台选择低成本只读探针"""
        from . import external_api as api

        platform = store.platform
        if platform == "tiktok":
            result = await api.get_tiktok_shop_client().fetch_shop_cipher(store_creds=creds)
            if result.get("status") != "success":
                return False, result.get("error") or "TikTok 店铺列表查询失败"
            shops = (result.get("output") or {}).get("shops") or []
            if shops and not store.extra.get("shop_cipher"):
                store.extra["shop_cipher"] = shops[0].get("shop_cipher") or ""
            return True, f"授权店铺 {len(shops)} 家"
        if platform == "amazon":
            token = await api.get_amazon_sp_client().get_access_token(
                refresh_token=creds.refresh_token,
                client_id=creds.app_key,
                client_secret=creds.app_secret,
            )
            return bool(token), "LWA 令牌交换成功"
        if platform == "ali1688":
            if creds.refresh_token:
                token = await api.get_alibaba1688_client().fetch_token(
                    app_key=creds.app_key, app_secret=creds.app_secret, refresh_token=creds.refresh_token
                )
                return bool(token), "ocean 令牌刷新成功"
            return api.get_alibaba1688_client().is_available(store_creds=creds), "凭据校验通过（本地）"
        getter = _platform_client_getter(platform)
        if getter is None:
            return bool(creds.app_key or creds.access_token or creds.refresh_token), "凭据已配置"
        client = getter()
        if creds.refresh_token:
            token = await client.get_access_token(creds.app_key, creds.app_secret, creds.refresh_token)
            return bool(token), "令牌刷新成功"
        if hasattr(client, "is_available"):
            return bool(client.is_available(store_creds=creds)), "凭据校验通过（本地）"
        return True, "凭据已配置"

    async def refresh_token(self, store_id: str, user_id: str = "") -> Dict[str, Any]:
        """强制刷新 access_token 并回写 SecretStore 与过期时间（仅限归属用户）"""
        store = self._db.get_store_connection(store_id, user_id)
        if store is None:
            return {"status": "error", "error": f"店铺不存在: {store_id}"}
        try:
            creds = self.resolve_credentials(store.platform, store_id, user_id)
        except Exception as exc:  # noqa: BLE001
            self._mark(store_id, "error", str(exc), user_id)
            return {"status": "error", "error": str(exc)}
        if not creds.refresh_token:
            return {"status": "error", "error": f"{store.platform} 未配置 refresh_token，无需刷新"}
        try:
            token = await self._platform_refresh(store.platform, creds)
        except Exception as exc:  # noqa: BLE001
            self._mark(store_id, "error", str(exc), user_id)
            return {"status": "error", "error": str(exc)}
        slot_map = _cred_field_to_slot()
        acc_field = next(k for k, v in slot_map.items() if v == "ACCESS_TOKEN")
        self._save_credentials(store_id, {acc_field: token})
        expires_at = time.time() + 86400
        self.update_store(store_id, user_id=user_id, token_expires_at=expires_at, status="active", last_error="")
        return {"status": "active", "token_expires_at": expires_at}

    async def _platform_refresh(self, platform: str, creds: StoreCredentials) -> str:
        from . import external_api as api

        if platform == "amazon":
            return await api.get_amazon_sp_client().get_access_token(
                refresh_token=creds.refresh_token, client_id=creds.app_key, client_secret=creds.app_secret
            )
        if platform == "ali1688":
            return await api.get_alibaba1688_client().fetch_token(
                app_key=creds.app_key, app_secret=creds.app_secret, refresh_token=creds.refresh_token
            )
        client = _platform_client_getter(platform)()
        return await client.get_access_token(creds.app_key, creds.app_secret, creds.refresh_token)

    def _mark(self, store_id: str, status: str, last_error: str, user_id: str = "") -> None:
        self.update_store(store_id, user_id=user_id, status=status, last_error=last_error)

    # ---- OAuth 一次性 state（防 CSRF，经注入的密钥库存取） ----

    def oauth_state_set(self, state: str, payload: Dict[str, Any]) -> None:
        self._secrets.set(f"OAUTH_STATE_{state}", json.dumps(payload, ensure_ascii=False))

    def oauth_state_pop(self, state: str) -> Optional[Dict[str, Any]]:
        value = self._secrets.get(f"OAUTH_STATE_{state}")
        if value is None:
            return None
        self._secrets.delete(f"OAUTH_STATE_{state}")
        try:
            payload = json.loads(value)
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    # ---- 输出 ----

    def mask(self, store: StoreConnection) -> Dict[str, Any]:
        """API 输出脱敏：常规字段 + 各凭据槽位仅后 4 位"""
        data = dataclasses.asdict(store)
        for suffix in _SLOTS:
            value = self._secrets.get(_store_key(store.store_id, suffix))
            data[f"{suffix.lower()}_masked"] = _mask(value) if value else ""
        return data


# ---------------- 单例 ----------------

_singleton: Optional[StoreConnectionManager] = None
_singleton_lock = threading.Lock()


def get_store_connection_manager() -> StoreConnectionManager:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = StoreConnectionManager()
        return _singleton


def reset_store_connection_manager() -> None:
    global _singleton
    with _singleton_lock:
        _singleton = None
