"""凭据按用户分桶（SSH 主机 / RDP 直连 / 通用键值共用）。

设计：
- 每用户一个凭据桶目录（base_dir/{user_id}/），凭据值经认证加密落盘
  （`secret_store_clean` 复用 `providers.secret_store` 的 AES-256-GCM 口径，明文不落磁盘）；
  加密 keyfile 首次生成后持久（重启稳定）
- 与全局配置的关系：不做全局 fallback。凭据一律按归属桶存取，
  单用户部署在 default 桶配置即可。
- 社交平台凭据段已退役（§6-591，2026-11-12）：social_search 登录态归上游
  agent-reach CLI 浏览器会话，本仓不再存社交凭据。平台键集注册表
  （PLATFORM_REQUIRED_KEYS／platform_credentials 批量读）随 §6-592 退役——
  RDP 换专用访问器（rdp::endpoint 单记录，同 SSH 形态）后注册表零消费者。
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, Optional

from neurova.core.data_root import callerPath
from neurova.core.logger import get_logger
from neurova.llm.providers.secret_store_clean import SecretStore
from neurova.security.local_key_protection import loadOrCreateKeyfile

logger = get_logger(__name__)

class UserCredentialStore:
    """按用户分桶的凭据存储（加密落盘，跨重启稳定）"""

    def __init__(self, base_dir: str = "", encryption_key: Optional[str] = None):
        # 空串默认值经数据根推导；裸 `Path("")` 会把加密 keyfile 与凭据桶建在 CWD。
        self.base_dir = callerPath(base_dir, "web_reach_credentials")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._cipher_key = encryption_key or self._load_or_create_keyfile()
        self._stores: Dict[str, SecretStore] = {}

    def _load_or_create_keyfile(self) -> str:
        """部署级 keyfile：Windows 走 DPAPI（密钥密文只属当前用户/机器）。

        旧明文 hex keyfile 在该入口就地迁移；解不开按错误抛出，不静默降级回明文。
        """
        return loadOrCreateKeyfile(self.base_dir / "_keyfile", purpose="web_reach credentials")

    def _store_for(self, user_id: str) -> SecretStore:
        uid = user_id or "default"
        with self._lock:
            if uid not in self._stores:
                bucket = self.base_dir / uid
                bucket.mkdir(parents=True, exist_ok=True)
                self._stores[uid] = SecretStore(
                    storage_path=str(bucket),
                    encryption_key=self._cipher_key,
                )
            return self._stores[uid]

    def set_credential(self, user_id: str, key: str, value: str) -> bool:
        if not user_id or not key or not value:
            return False
        return self._store_for(user_id).store_secret(
            name=key,
            value=value,
            description=f"web_reach credential for user={user_id}",
            tags=["web_reach", user_id],
        )

    def get_credential(self, user_id: str, key: str) -> Optional[str]:
        return self._store_for(user_id).get_secret(key)

    def delete_credential(self, user_id: str, key: str) -> bool:
        return self._store_for(user_id).delete_secret(key)

    # ── SSH 多主机凭据（按 host 分键，computer_ssh_exec 消费）──────────
    # 值以 JSON 存于加密桶：{"user","port","key_text","password"}；GET 永不回显密钥/密码。

    _SSH_PREFIX = "ssh::"

    def set_ssh_host(
        self, user_id: str, host: str, *, user: Optional[str] = None, port: int = 22,
        key_text: Optional[str] = None, password: Optional[str] = None,
    ) -> bool:
        host = (host or "").strip()
        if not host:
            return False
        payload = {
            "user": (user or "").strip(),
            "port": int(port or 22),
            "key_text": key_text or "",
            "password": password or "",
        }
        return self.set_credential(user_id, self._SSH_PREFIX + host, json.dumps(payload, ensure_ascii=False))

    def get_ssh_host(self, user_id: str, host: str) -> Dict[str, Any]:
        raw = self.get_credential(user_id, self._SSH_PREFIX + (host or "").strip())
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            return {}

    def list_ssh_hosts(self, user_id: str) -> list:
        """列出该用户已配置的 SSH 主机（脱敏：只回 host/user/port/auth 类型，不回密钥/密码）。"""
        try:
            secrets = self._store_for(user_id).list_secrets() or []
        except Exception:  # noqa: BLE001
            return []
        out = []
        for meta in secrets:
            name = meta.get("name", "") if isinstance(meta, dict) else ""
            if not name.startswith(self._SSH_PREFIX):
                continue
            host = name[len(self._SSH_PREFIX):]
            cfg = self.get_ssh_host(user_id, host)
            auth = "key" if cfg.get("key_text") else ("password" if cfg.get("password") else "agent")
            out.append({
                "host": host,
                "user": cfg.get("user", ""),
                "port": cfg.get("port", 22),
                "auth": auth,
            })
        out.sort(key=lambda r: r["host"])
        return out

    def delete_ssh_host(self, user_id: str, host: str) -> bool:
        return self.delete_credential(user_id, self._SSH_PREFIX + (host or "").strip())

    # ── RDP 直连凭据（单记录 rdp::endpoint，rdp_provider 消费；§6-592 接通）──
    # 值以 JSON 存于加密桶：{"host","port","token"}；status/GET 永不回显 token。

    _RDP_KEY = "rdp::endpoint"

    def set_rdp_endpoint(self, user_id: str, *, host: str, port: int = 8765, token: str = "") -> bool:
        """写入/更新 RDP 直连端点（host 必填；token 空值不覆盖已设值）。"""
        host = (host or "").strip()
        if not host:
            return False
        existing = self.get_rdp_endpoint(user_id)
        payload = {
            "host": host,
            "port": int(port or 8765),
            "token": token if token else (existing.get("token") or ""),
        }
        return self.set_credential(user_id, self._RDP_KEY, json.dumps(payload, ensure_ascii=False))

    def get_rdp_endpoint(self, user_id: str) -> Dict[str, Any]:
        raw = self.get_credential(user_id, self._RDP_KEY)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            return {}

    def rdp_status(self, user_id: str) -> Dict[str, Any]:
        """脱敏读数：configured/host/port/token_set，永不回显 token。"""
        ep = self.get_rdp_endpoint(user_id)
        return {
            "configured": bool(ep.get("host")),
            "host": ep.get("host", ""),
            "port": int(ep.get("port") or 8765),
            "token_set": bool(ep.get("token")),
        }

    def delete_rdp_endpoint(self, user_id: str) -> bool:
        return self.delete_credential(user_id, self._RDP_KEY)


# 模块级单例工厂（SSH/RDP provider 与设置端点共用）
_credential_store_instance: Optional[UserCredentialStore] = None
_credential_store_lock = threading.Lock()


def get_credential_store(base_dir: str = "") -> UserCredentialStore:
    global _credential_store_instance
    if _credential_store_instance is None:
        with _credential_store_lock:
            if _credential_store_instance is None:
                _credential_store_instance = UserCredentialStore(base_dir=base_dir)
    return _credential_store_instance


def reset_credential_store() -> None:
    global _credential_store_instance
    with _credential_store_lock:
        _credential_store_instance = None
