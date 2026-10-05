"""
Agent API密钥管理模块

功能:
1. 生成36位随机字符API密钥
2. API密钥与Agent绑定（用户隔离）
3. API密钥的CRUD操作
4. 密钥验证和权限控制

集成现有认证系统（neurova/api/auth.py）
"""

import atexit
import hashlib
import json
import os
import secrets
import threading
import time
from datetime import datetime
from dataclasses import asdict, field, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger
from neurova.core.data_root import callerPath

logger = get_logger(__name__)


@dataclass
class APIKey:
    """API密钥数据

    时间字段兼容 float（epoch 秒，管理器内部使用）与 datetime（外部调用方），
    序列化时统一为 ISO 字符串。
    """

    key_id: str
    agent_id: str
    user_id: str
    key_hash: str  # SHA-256 哈希
    name: str
    created_at: Any  # float epoch 或 datetime
    expires_at: Any = None  # Optional[float | datetime]
    last_used_at: Any = None
    is_active: bool = True
    permissions: List[str] = field(default_factory=lambda: ["read", "write"])
    rate_limit: int = 1000
    metadata: Dict[str, Any] = field(default_factory=dict)
    key_prefix: str = ""  # 前8位，用于显示
    # 以下五项自 openplatform_keys 的私有存储并入（教义第 7 条"取长补短"）：
    # 那一份实现带这三样本管理器没有的机制——原子写、创建幂等、撤销 tombstone，
    # 并入后两套密钥共用同一份实现，仓内不再各存一本账。
    description: str = ""
    usage_count: int = 0
    creation_request_id: Optional[str] = None  # 客户端幂等键
    intent_hash: str = ""  # 创建意图指纹（同幂等键不同意图 = 409）
    revoked_at: Any = None

    def __post_init__(self):
        if isinstance(self.permissions, str):
            self.permissions = [self.permissions]
        if self.metadata is None:
            self.metadata = {}

    @staticmethod
    def _to_iso(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    @staticmethod
    def _parse_time(value: Any) -> Any:
        if value is None or isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None

    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.expires_at is None:
            return False
        expires = self._parse_time(self.expires_at)
        if isinstance(expires, datetime):
            return datetime.now() > expires
        return time.time() > float(expires)

    def touch(self):
        """更新最后使用时间"""
        self.last_used_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（含 key_hash，供持久化；对外展示应自行剥离）"""
        return {
            "key_id": self.key_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "key_hash": self.key_hash,
            "key_prefix": self.key_prefix,
            "name": self.name,
            "permissions": list(self.permissions),
            "rate_limit": self.rate_limit,
            "created_at": self._to_iso(self.created_at),
            "expires_at": self._to_iso(self.expires_at),
            "last_used_at": self._to_iso(self.last_used_at),
            "is_active": self.is_active,
            "metadata": self.metadata,
            "description": self.description,
            "usage_count": self.usage_count,
            "creation_request_id": self.creation_request_id,
            "intent_hash": self.intent_hash,
            "revoked_at": self._to_iso(self.revoked_at),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "APIKey":
        """从字典恢复（ISO 时间字符串自动解析为 datetime）"""
        known = {
            "key_id", "agent_id", "user_id", "key_hash", "key_prefix", "name",
            "permissions", "rate_limit", "created_at", "expires_at",
            "last_used_at", "is_active", "metadata",
            "description", "usage_count", "creation_request_id", "intent_hash",
            "revoked_at",
        }
        filtered = {k: v for k, v in data.items() if k in known}
        filtered["created_at"] = cls._parse_time(filtered.get("created_at")) or time.time()
        filtered["expires_at"] = cls._parse_time(filtered.get("expires_at"))
        filtered["last_used_at"] = cls._parse_time(filtered.get("last_used_at"))
        if "revoked_at" in filtered:
            filtered["revoked_at"] = cls._parse_time(filtered["revoked_at"])
        return cls(**filtered)



class APIKeyManager:
    """
    API密钥管理器

    管理Agent的API密钥，支持生成、验证、撤销等功能。
    """

    # touch 类轻量变更（validate_key 更新 last_used_at）的落盘防抖间隔（秒）。
    # S-19：validate_key 高频命中时每次全量 JSON 重写会放大 IO，改为脏标记 + 防抖。
    SAVE_DEBOUNCE_SECONDS = 30.0

    def __init__(self, storage_path: Optional[Path] = None, key_length: int = 36, default_expiry_days: int = 365, key_namespace: str = ""):
        """
        初始化API密钥管理器

        Args:
            storage_path: 存储路径
            key_length: 密钥长度
            default_expiry_days: 默认过期天数
            key_namespace: 密钥明文前缀（开放平台用 `nrv_`，agent 域留空）。
                同一份实现按命名空间分区，不为区分产品线再写第二本密钥账。
        """
        self.storage_path = callerPath(storage_path, "api_keys.json")
        self.key_length = key_length
        self.default_expiry_days = default_expiry_days
        self.key_namespace = key_namespace

        # 密钥存储
        self._keys: Dict[str, APIKey] = {}  # key_id -> APIKey
        self._key_hash_index: Dict[str, str] = {}  # key_hash -> key_id

        # 线程安全
        self._lock = threading.RLock()

        # S-19：touch 类变更的脏标记 + 防抖落盘状态
        self._dirty = False
        self._last_save_ts = 0.0
        self._save_timer: Optional[threading.Timer] = None

        # 加载密钥
        self._load_keys()

        # S-19：进程退出时把未落盘的内存态（last_used_at 等）flush 到存储
        atexit.register(self._flush_on_exit)

        logger.info("APIKeyManager 初始化，存储路径: %s", self.storage_path)

    def _load_keys(self):
        """从存储加载密钥

        两种形状都读：`{"keys": [...]}`（本管理器的写法）与**扁平 dict**
        （openplatform_keys 私有存储的历史形状）。合并实现后部署侧已有的
        `openplatform_keys.json` 不得变成孤儿文件——那等于把用户已发的密钥读丢。
        损坏文件先备份留证再空载，禁止静默清空（教义第 2 条）。
        """
        try:
            if not self.storage_path.exists():
                return
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                backup = self.storage_path.with_name(
                    f"{self.storage_path.name}.corrupt-{int(time.time())}"
                )
                try:
                    self.storage_path.replace(backup)
                    logger.error("API 密钥库损坏，已备份 %s 后空载: %s", backup, e)
                except OSError:
                    logger.error("API 密钥库损坏且备份失败: %s", e)
                return

            if isinstance(data, dict) and "keys" in data:
                records = data.get("keys") or []
            else:
                # 扁平形状：{key_id: {...}}；老记录缺 key_id 用其字典键补齐，
                # 缺 agent_id（开放平台密钥本就没有 agent）用归属者占位
                records = [
                    {
                        **value,
                        "key_id": value.get("key_id") or key_name,
                        "agent_id": value.get("agent_id") or value.get("user_id", ""),
                    }
                    for key_name, value in (data or {}).items()
                    if isinstance(value, dict)
                ]

            for key_data in records:
                # 逐条容错：一条坏记录不得把整库读丢（原实现是整段 try 包住，
                # 任何一条抛异常就退回"零把密钥"，且只有一行 ERROR 可查）
                try:
                    api_key = APIKey.from_dict(key_data)
                except Exception as e:  # noqa: BLE001 - 单条损坏不影响其余装载
                    logger.error(
                        "跳过无法解析的密钥记录 %s: %s", key_data.get("key_id") if isinstance(key_data, dict) else "?", e
                    )
                    continue
                self._keys[api_key.key_id] = api_key
                self._key_hash_index[api_key.key_hash] = api_key.key_id

            logger.info("加载了 %s 个API密钥", len(self._keys))
        except Exception as e:
            logger.error("加载API密钥失败: %s", e)

    def find_by_creation_request_id(self, user_id: str, request_id: str) -> Optional[APIKey]:
        """按 (用户, 幂等键) 找回既有密钥——供端点判"重放 / 意图冲突 / tombstone"。

        幂等决策属 HTTP 语义，留在端点；存储层只负责把这一份事实如实给出。
        """
        if not request_id:
            return None
        with self._lock:
            for api_key in self._keys.values():
                if api_key.user_id == user_id and api_key.creation_request_id == request_id:
                    return api_key
        return None

    def _save_keys(self):
        """保存密钥到存储"""
        try:
            # 确保目录存在
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)

            # 准备数据
            data = {"keys": [key.to_dict() for key in self._keys.values()], "updated_at": time.time()}

            # 原子写：temp + os.replace（自 openplatform_keys 并入）。
            # 直接覆盖写进程被中断会留下半截 JSON，下次启动就是"密钥全丢"。
            tmp = self.storage_path.with_name(self.storage_path.name + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.storage_path)

            # 全量落盘完成，脏状态复位（S-19）
            self._dirty = False
            self._last_save_ts = time.time()

            logger.debug("保存了 %s 个API密钥", len(self._keys))
        except Exception as e:
            logger.error("保存API密钥失败: %s", e)

    def _schedule_save(self):
        """S-19：touch 类轻量变更的防抖落盘——SAVE_DEBOUNCE_SECONDS 内至多写一次盘"""
        self._dirty = True
        elapsed = time.time() - self._last_save_ts
        if elapsed >= self.SAVE_DEBOUNCE_SECONDS:
            self._save_keys()
            return
        if self._save_timer is None:
            timer = threading.Timer(self.SAVE_DEBOUNCE_SECONDS - elapsed, self._flush_dirty)
            timer.daemon = True
            self._save_timer = timer
            timer.start()

    def _flush_dirty(self):
        """防抖定时器回调：仍有脏数据时落盘一次"""
        with self._lock:
            self._save_timer = None
            if not self._dirty:
                return
            self._save_keys()

    def flush(self):
        """立即落盘未持久化的脏状态（S-19：供进程退出/关键节点调用）"""
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
            if self._dirty:
                self._save_keys()

    def _flush_on_exit(self):
        """进程退出钩子：把内存态 last_used_at flush 到存储"""
        try:
            self.flush()
        except Exception as e:
            logger.warning("进程退出时落盘API密钥失败: %s", e)

    def generate_key(
        self,
        agent_id: str,
        user_id: str,
        name: str,
        permissions: List[str],
        expires_in_days: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        description: str = "",
        creation_request_id: Optional[str] = None,
        intent_hash: str = "",
    ) -> Tuple[str, APIKey]:
        """
        生成API密钥

        Args:
            agent_id: Agent ID
            user_id: 用户ID
            name: 密钥名称
            permissions: 权限列表
            expires_in_days: 过期天数
            metadata: 元数据
            description: 用途说明（开放平台口径）
            creation_request_id: 客户端幂等键（重放由端点判 409/回放，见
                `find_by_creation_request_id`）
            intent_hash: 创建意图指纹，用于识破"同幂等键换意图"

        Returns:
            (原始密钥, APIKey对象)
        """
        with self._lock:
            # 生成随机密钥（带命名空间前缀时，前缀即产品线标识）
            raw_key = f"{self.key_namespace}{secrets.token_urlsafe(self.key_length)}"

            # 计算哈希
            key_hash = self._hash_key(raw_key)

            # 生成密钥ID
            key_id = f"ak_{secrets.token_hex(16)}"

            # 计算过期时间
            expires_at = None
            if expires_in_days is None:
                expires_in_days = self.default_expiry_days

            if expires_in_days > 0:
                expires_at = time.time() + (expires_in_days * 24 * 3600)

            # 创建APIKey对象
            api_key = APIKey(
                key_id=key_id,
                key_hash=key_hash,
                key_prefix=raw_key[:8],
                agent_id=agent_id,
                user_id=user_id,
                name=name,
                permissions=permissions,
                created_at=time.time(),
                expires_at=expires_at,
                metadata=metadata,
                description=description,
                creation_request_id=creation_request_id,
                intent_hash=intent_hash,
            )

            # 存储
            self._keys[key_id] = api_key
            self._key_hash_index[key_hash] = key_id

            # 保存
            self._save_keys()

            logger.info("生成API密钥: %s for agent %s", key_id, agent_id)

            return raw_key, api_key

    def validate_key(self, raw_key: str) -> Optional[APIKey]:
        """
        验证API密钥

        Args:
            raw_key: 原始密钥

        Returns:
            APIKey对象，无效返回None
        """
        with self._lock:
            # 计算哈希
            key_hash = self._hash_key(raw_key)

            # 查找密钥
            key_id = self._key_hash_index.get(key_hash)
            if not key_id:
                return None

            api_key = self._keys.get(key_id)
            if not api_key:
                return None

            # 检查状态
            if not api_key.is_active:
                return None

            # 检查是否过期
            if api_key.is_expired():
                return None

            # 更新使用时间（S-19：仅内存态 + 脏标记，防抖落盘，不再每次全量重写 JSON）
            api_key.touch()
            api_key.usage_count += 1
            self._schedule_save()

            return api_key

    def get_key_by_id(self, key_id: str) -> Optional[APIKey]:
        """
        根据ID获取密钥

        Args:
            key_id: 密钥ID

        Returns:
            APIKey对象
        """
        with self._lock:
            return self._keys.get(key_id)

    def get_agent_keys(self, agent_id: str) -> List[APIKey]:
        """
        获取Agent的所有密钥

        Args:
            agent_id: Agent ID

        Returns:
            密钥列表
        """
        with self._lock:
            return [key for key in self._keys.values() if key.agent_id == agent_id]

    def get_user_keys(self, user_id: str) -> List[APIKey]:
        """
        获取用户的所有密钥

        Args:
            user_id: 用户ID

        Returns:
            密钥列表
        """
        with self._lock:
            return [key for key in self._keys.values() if key.user_id == user_id]

    def update_key(
        self,
        key_id: str,
        name: Optional[str] = None,
        permissions: Optional[List[str]] = None,
        expires_at: Optional[float] = None,
        is_active: Optional[bool] = None,
        description: Optional[str] = None,
    ) -> Optional[APIKey]:
        """
        更新密钥

        Args:
            key_id: 密钥ID
            name: 新名称
            permissions: 新权限
            expires_at: 新过期时间
            is_active: 启用/停用（开放平台的 enabled 口径落在这里）
            description: 新用途说明

        Returns:
            更新后的APIKey对象
        """
        with self._lock:
            api_key = self._keys.get(key_id)
            if not api_key:
                return None

            if name is not None:
                api_key.name = name

            if permissions is not None:
                api_key.permissions = permissions

            if expires_at is not None:
                api_key.expires_at = expires_at

            if is_active is not None:
                api_key.is_active = bool(is_active)

            if description is not None:
                api_key.description = description

            self._save_keys()

            logger.info("更新API密钥: %s", key_id)
            return api_key

    def revoke_key(self, key_id: str) -> bool:
        """
        撤销密钥

        Args:
            key_id: 密钥ID

        Returns:
            是否成功
        """
        with self._lock:
            api_key = self._keys.get(key_id)
            if not api_key:
                return False

            api_key.is_active = False
            # tombstone 留痕：撤销时间入档，行保留不物理删——物理删会让同一幂等键的
            # 重放绕过"已撤销不得复活"这道检查（自 openplatform_keys 并入）
            api_key.revoked_at = time.time()
            self._save_keys()

            logger.info("撤销API密钥: %s", key_id)
            return True

    def delete_key(self, key_id: str) -> bool:
        """
        删除密钥

        Args:
            key_id: 密钥ID

        Returns:
            是否成功
        """
        with self._lock:
            api_key = self._keys.get(key_id)
            if not api_key:
                return False

            # 从索引中移除
            if api_key.key_hash in self._key_hash_index:
                del self._key_hash_index[api_key.key_hash]

            # 从存储中移除
            del self._keys[key_id]

            self._save_keys()

            logger.info("删除API密钥: %s", key_id)
            return True

    def check_permission(self, raw_key: str, permission: str) -> bool:
        """
        检查权限

        Args:
            raw_key: 原始密钥
            permission: 权限

        Returns:
            是否有权限
        """
        api_key = self.validate_key(raw_key)
        if not api_key:
            return False

        # 检查权限
        if "*" in api_key.permissions:
            return True

        return permission in api_key.permissions

    def _hash_key(self, raw_key: str) -> str:
        """
        计算密钥哈希

        Args:
            raw_key: 原始密钥

        Returns:
            SHA-256哈希
        """
        return hashlib.sha256(raw_key.encode()).hexdigest()

    def cleanup_expired_keys(self) -> int:
        """
        清理过期密钥

        Returns:
            清理的密钥数量
        """
        with self._lock:
            expired_keys = []

            for key_id, api_key in self._keys.items():
                if api_key.is_expired():
                    expired_keys.append(key_id)

            for key_id in expired_keys:
                api_key = self._keys[key_id]

                # 从索引中移除
                if api_key.key_hash in self._key_hash_index:
                    del self._key_hash_index[api_key.key_hash]

                # 从存储中移除
                del self._keys[key_id]

            if expired_keys:
                self._save_keys()
                logger.info("清理了 %s 个过期密钥", len(expired_keys))

            return len(expired_keys)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            total_keys = len(self._keys)
            active_keys = sum(1 for k in self._keys.values() if k.is_active and not k.is_expired())
            expired_keys = sum(1 for k in self._keys.values() if k.is_expired())

            return {
                "total_keys": total_keys,
                "active_keys": active_keys,
                "expired_keys": expired_keys,
                "timestamp": time.time(),
            }


# 单例管理
_api_key_manager_instance: Optional[APIKeyManager] = None
_api_key_manager_lock = threading.Lock()


def get_api_key_manager(**kwargs) -> APIKeyManager:
    """获取API密钥管理器单例"""
    global _api_key_manager_instance

    if _api_key_manager_instance is None:
        with _api_key_manager_lock:
            if _api_key_manager_instance is None:
                _api_key_manager_instance = APIKeyManager(**kwargs)

    return _api_key_manager_instance


def reset_api_key_manager():
    """重置API密钥管理器单例"""
    global _api_key_manager_instance

    with _api_key_manager_lock:
        _api_key_manager_instance = None
