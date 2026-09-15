"""社交平台凭据按用户分桶（三层隔离遗留项修复）。

设计：
- 每用户一个凭据桶目录（base_dir/{user_id}/），凭据值经 SimpleCipher 加密
  落盘（明文不落磁盘）；加密 keyfile 首次生成后持久（重启稳定）
- agent-reach Config 的 config_path 可指向用户桶（user_config_path）——
  上游以 HOME/config_path 作为凭据隔离边界（官方姿势）
- 与全局配置的关系：不做全局 fallback。凭据一律按归属桶存取，
  单用户部署在 default 桶配置即可。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger
from neurova.llm.providers.secret_store_clean import SecretStore

logger = get_logger(__name__)

# 凭据 key → 平台（list_platforms 聚合用）
_KEY_TO_PLATFORM = {
    "twitter_auth_token": "twitter",
    "twitter_ct0": "twitter",
    "reddit_session": "reddit",
    "xiaohongshu_cookie": "xiaohongshu",
    "facebook_cookie": "facebook",
    "instagram_cookie": "instagram",
    "linkedin_cookie": "linkedin",
    "github_token": "github",
}

# 平台 → 所需凭据 keys（齐备才算"已配置"；social_exec 同源使用）
PLATFORM_REQUIRED_KEYS = {
    "twitter": ["twitter_auth_token", "twitter_ct0"],
    "reddit": ["reddit_session"],
    "xiaohongshu": ["xiaohongshu_cookie"],
    "facebook": ["facebook_cookie"],
    "instagram": ["instagram_cookie"],
    "linkedin": ["linkedin_cookie"],
    "github": ["github_token"],
}


def user_config_path(user_id: str, base_dir: str = "data/web_reach_credentials") -> Path:
    """用户桶内的 agent-reach config.yaml 路径（Config(config_path=...) 用）"""
    return Path(base_dir) / (user_id or "default") / "config.yaml"


class UserCredentialStore:
    """按用户分桶的凭据存储（加密落盘，跨重启稳定）"""

    def __init__(self, base_dir: str = "data/web_reach_credentials", encryption_key: Optional[str] = None):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._cipher_key = encryption_key or self._load_or_create_keyfile()
        self._stores: Dict[str, SecretStore] = {}

    def _load_or_create_keyfile(self) -> str:
        """部署级 keyfile：首次生成随机密钥并持久，重启/迁移随文件走"""
        keyfile = self.base_dir / "_keyfile"
        if keyfile.exists():
            return keyfile.read_text(encoding="utf-8").strip()
        import secrets as _secrets

        key = _secrets.token_hex(32)
        keyfile.write_text(key, encoding="utf-8")
        try:
            import stat as _stat

            os.chmod(keyfile, _stat.S_IRUSR | _stat.S_IWUSR)
        except Exception:  # noqa: BLE001 - Windows 无 POSIX 权限位
            pass
        logger.info("Generated credential keyfile: %s", keyfile)
        return key

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

    def platform_credentials(self, user_id: str, platform: str) -> Dict[str, str]:
        """取某平台所需的全部凭据 keys（缺失项以 None 占位）"""
        required = PLATFORM_REQUIRED_KEYS.get((platform or "").lower(), [])
        return {k: self.get_credential(user_id, k) for k in required}

    def list_platforms(self, user_id: str) -> Dict[str, bool]:
        """按平台聚合配置状态（该平台所需凭据全部齐备 = True）"""
        creds: Dict[str, Optional[str]] = {}
        result: Dict[str, bool] = {}
        for key, platform in _KEY_TO_PLATFORM.items():
            creds[key] = self.get_credential(user_id, key)
        for platform, required in PLATFORM_REQUIRED_KEYS.items():
            result[platform] = all(creds.get(k) for k in required)
        return result

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

    # ── 社交平台凭据（web_reach social_exec 消费；与 SSH 复用同一加密桶/配置面）──

    def set_platform_credentials(self, user_id: str, platform: str, mapping: Dict[str, str]) -> bool:
        """按平台批量存凭据（只接受该平台所需键，多余键忽略）。"""
        required = PLATFORM_REQUIRED_KEYS.get((platform or "").strip().lower())
        if not required:
            return False
        ok = True
        for key in required:
            val = (mapping or {}).get(key)
            if val:  # 空值不覆盖已有（允许部分更新）
                ok = self.set_credential(user_id, key, str(val)) and ok
        return ok

    def platform_status(self, user_id: str) -> list:
        """各平台凭据配置状态（脱敏：只回键名 + 是否已配，不回值）。"""
        out = []
        for platform, required in PLATFORM_REQUIRED_KEYS.items():
            keys = [{"key": k, "set": bool(self.get_credential(user_id, k))} for k in required]
            out.append({"platform": platform, "keys": keys, "configured": all(k["set"] for k in keys)})
        out.sort(key=lambda r: r["platform"])
        return out

    def clear_platform_credentials(self, user_id: str, platform: str) -> int:
        required = PLATFORM_REQUIRED_KEYS.get((platform or "").strip().lower(), [])
        return sum(1 for k in required if self.delete_credential(user_id, k))


# 模块级单例工厂（reach 与 executor 共用）
_credential_store_instance: Optional[UserCredentialStore] = None
_credential_store_lock = threading.Lock()


def get_credential_store(base_dir: str = "data/web_reach_credentials") -> UserCredentialStore:
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
