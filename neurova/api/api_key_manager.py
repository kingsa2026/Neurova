"""
Agent API密钥管理模块

功能:
1. 生成36位随机字符API密钥
2. API密钥与Agent绑定（用户隔离）
3. API密钥的CRUD操作
4. 密钥验证和权限控制

集成现有认证系统（neurova/api/auth.py）
"""

import datetime
import hashlib
import json
import logging
import secrets
import time
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from neurova.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class APIKey:
    """API密钥数据"""
    key_id: str
    key_hash: str  # SHA-256 哈希
    key_prefix: str  # 前8位，用于显示
    agent_id: str
    user_id: str
    name: str
    permissions: List[str]
    created_at: float
    expires_at: Optional[float] = None
    last_used_at: Optional[float] = None
    is_active: bool = True
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    def touch(self):
        """更新最后使用时间"""
        self.last_used_at = time.time()


class APIKeyManager:
    """
    API密钥管理器
    
    管理Agent的API密钥，支持生成、验证、撤销等功能。
    """
    
    def __init__(
        self,
        storage_path: Optional[Path] = None,
        key_length: int = 36,
        default_expiry_days: int = 365
    ):
        """
        初始化API密钥管理器
        
        Args:
            storage_path: 存储路径
            key_length: 密钥长度
            default_expiry_days: 默认过期天数
        """
        self.storage_path = storage_path or Path("data/api_keys.json")
        self.key_length = key_length
        self.default_expiry_days = default_expiry_days
        
        # 密钥存储
        self._keys: Dict[str, APIKey] = {}  # key_id -> APIKey
        self._key_hash_index: Dict[str, str] = {}  # key_hash -> key_id
        
        # 线程安全
        self._lock = threading.RLock()
        
        # 加载密钥
        self._load_keys()
        
        logger.info(f"APIKeyManager 初始化，存储路径: {self.storage_path}")
    
    def _load_keys(self):
        """从存储加载密钥"""
        try:
            if self.storage_path.exists():
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                for key_data in data.get('keys', []):
                    api_key = APIKey(**key_data)
                    self._keys[api_key.key_id] = api_key
                    self._key_hash_index[api_key.key_hash] = api_key.key_id
                
                logger.info(f"加载了 {len(self._keys)} 个API密钥")
        except Exception as e:
            logger.error(f"加载API密钥失败: {e}")
    
    def _save_keys(self):
        """保存密钥到存储"""
        try:
            # 确保目录存在
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 准备数据
            data = {
                'keys': [key.to_dict() for key in self._keys.values()],
                'updated_at': time.time()
            }
            
            # 写入文件
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"保存了 {len(self._keys)} 个API密钥")
        except Exception as e:
            logger.error(f"保存API密钥失败: {e}")
    
    def generate_key(
        self,
        agent_id: str,
        user_id: str,
        name: str,
        permissions: List[str],
        expires_in_days: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
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
            
        Returns:
            (原始密钥, APIKey对象)
        """
        with self._lock:
            # 生成随机密钥
            raw_key = secrets.token_urlsafe(self.key_length)
            
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
                metadata=metadata
            )
            
            # 存储
            self._keys[key_id] = api_key
            self._key_hash_index[key_hash] = key_id
            
            # 保存
            self._save_keys()
            
            logger.info(f"生成API密钥: {key_id} for agent {agent_id}")
            
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
            
            # 更新使用时间
            api_key.touch()
            self._save_keys()
            
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
        expires_at: Optional[float] = None
    ) -> Optional[APIKey]:
        """
        更新密钥
        
        Args:
            key_id: 密钥ID
            name: 新名称
            permissions: 新权限
            expires_at: 新过期时间
            
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
            
            self._save_keys()
            
            logger.info(f"更新API密钥: {key_id}")
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
            self._save_keys()
            
            logger.info(f"撤销API密钥: {key_id}")
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
            
            logger.info(f"删除API密钥: {key_id}")
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
                logger.info(f"清理了 {len(expired_keys)} 个过期密钥")
            
            return len(expired_keys)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            total_keys = len(self._keys)
            active_keys = sum(1 for k in self._keys.values() if k.is_active and not k.is_expired())
            expired_keys = sum(1 for k in self._keys.values() if k.is_expired())
            
            return {
                'total_keys': total_keys,
                'active_keys': active_keys,
                'expired_keys': expired_keys,
                'timestamp': time.time()
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