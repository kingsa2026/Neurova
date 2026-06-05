from __future__ import annotations

"""
Neurova 邀请码模型

用于管理注册邀请码
支持:
- 邀请码生成与验证
- 邀请码有效期管理
- 邀请码使用次数限制
- 邀请码类型（一次性/多次使用）
"""

from dataclasses import dataclass, asdict
import datetime
import enum
import logging
import os
import typing
from typing import Any, Dict, List, Optional

from enum import Enum
import secrets
import sqlite3
import time

logger = logging.getLogger(__name__)


class InvitationCodeType(Enum):
    """邀请码类型"""
    SINGLE_USE = "single_use"  # 一次性使用
    MULTI_USE = "multi_use"    # 多次使用
    UNLIMITED = "unlimited"    # 无限制使用


@dataclass
class InvitationCode:
    """邀请码数据模型"""
    code: str
    code_type: InvitationCodeType
    created_at: float
    expires_at: Optional[float] = None
    max_uses: int = 1
    current_uses: int = 0
    created_by: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result['code_type'] = self.code_type.value
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InvitationCode':
        """从字典创建"""
        data = data.copy()
        data['code_type'] = InvitationCodeType(data['code_type'])
        return cls(**data)
    
    @property
    def is_expired(self) -> bool:
        """是否已过期"""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    @property
    def is_used_up(self) -> bool:
        """是否已用完"""
        if self.code_type == InvitationCodeType.UNLIMITED:
            return False
        return self.current_uses >= self.max_uses
    
    @property
    def is_valid(self) -> bool:
        """是否有效"""
        return self.is_active and not self.is_expired and not self.is_used_up
    
    def can_be_used(self) -> bool:
        """是否可以使用"""
        return self.is_valid


class InvitationCodeModel:
    """
    邀请码管理模型
    负责邀请码的生成、验证、使用和管理
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        初始化邀请码管理器
        
        Args:
            db_path: 数据库文件路径
        """
        if db_path is None:
            # 默认数据库路径
            db_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, 'invitation_codes.db')
        
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_db_dir()
        self._init_db()
        
        logger.info("InvitationCodeModel initialized with db_path=%s", db_path)
    
    def _ensure_db_dir(self):
        """确保数据库目录存在"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
    
    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn
    
    def _init_db(self):
        """初始化数据库表"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # 创建邀请码表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS invitation_codes (
                code TEXT PRIMARY KEY,
                code_type TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL,
                max_uses INTEGER NOT NULL DEFAULT 1,
                current_uses INTEGER NOT NULL DEFAULT 0,
                created_by TEXT,
                description TEXT,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                metadata TEXT
            )
        ''')
        
        # 创建使用记录表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS invitation_code_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                used_at REAL NOT NULL,
                used_by TEXT,
                user_agent TEXT,
                ip_address TEXT,
                FOREIGN KEY (code) REFERENCES invitation_codes (code)
            )
        ''')
        
        # 创建索引
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_invitation_codes_expires_at 
            ON invitation_codes (expires_at)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_invitation_codes_is_active 
            ON invitation_codes (is_active)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_invitation_code_usage_code 
            ON invitation_code_usage (code)
        ''')
        
        conn.commit()
        logger.info("Database initialized successfully")
    
    def _generate_code(self, length: int = 8) -> str:
        """
        生成随机邀请码
        
        Args:
            length: 邀请码长度
            
        Returns:
            随机邀请码
        """
        # 使用容易阅读的字符（排除0/O/1/I/l等易混淆字符）
        chars = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
        code = ''.join(secrets.choice(chars) for _ in range(length))
        
        # 确保不重复
        while self.get_code(code) is not None:
            code = ''.join(secrets.choice(chars) for _ in range(length))
        
        return code
    
    def create_code(
        self,
        code_type: InvitationCodeType = InvitationCodeType.SINGLE_USE,
        max_uses: int = 1,
        expires_in: Optional[float] = None,  # 秒
        created_by: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        custom_code: Optional[str] = None
    ) -> InvitationCode:
        """
        创建邀请码
        
        Args:
            code_type: 邀请码类型
            max_uses: 最大使用次数
            expires_in: 过期时间（秒）
            created_by: 创建者
            description: 描述
            metadata: 元数据
            custom_code: 自定义邀请码（可选）
            
        Returns:
            创建的邀请码
        """
        try:
            # 生成或使用自定义邀请码
            code = custom_code if custom_code else self._generate_code()
            
            # 计算过期时间
            expires_at = None
            if expires_in is not None:
                expires_at = time.time() + expires_in
            
            # 创建邀请码对象
            invitation_code = InvitationCode(
                code=code,
                code_type=code_type,
                created_at=time.time(),
                expires_at=expires_at,
                max_uses=max_uses,
                current_uses=0,
                created_by=created_by,
                description=description,
                is_active=True,
                metadata=metadata
            )
            
            # 保存到数据库
            conn = self._get_conn()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO invitation_codes 
                (code, code_type, created_at, expires_at, max_uses, current_uses, 
                 created_by, description, is_active, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                invitation_code.code,
                invitation_code.code_type.value,
                invitation_code.created_at,
                invitation_code.expires_at,
                invitation_code.max_uses,
                invitation_code.current_uses,
                invitation_code.created_by,
                invitation_code.description,
                invitation_code.is_active,
                str(invitation_code.metadata) if invitation_code.metadata else None
            ))
            
            conn.commit()
            
            logger.info("Created invitation code: %s (type=%s)", code, code_type.value)
            return invitation_code
            
        except Exception as e:
            logger.error("Failed to create invitation code: %s", e)
            raise
    
    def get_code(self, code: str) -> Optional[InvitationCode]:
        """
        获取邀请码信息
        
        Args:
            code: 邀请码
            
        Returns:
            邀请码信息，如果不存在则返回None
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM invitation_codes WHERE code = ?
            ''', (code,))
            
            row = cursor.fetchone()
            if row is None:
                return None
            
            # 转换为邀请码对象
            metadata = None
            if row['metadata']:
                try:
                    import ast
                    metadata = ast.literal_eval(row['metadata'])
                except:
                    metadata = None
            
            return InvitationCode(
                code=row['code'],
                code_type=InvitationCodeType(row['code_type']),
                created_at=row['created_at'],
                expires_at=row['expires_at'],
                max_uses=row['max_uses'],
                current_uses=row['current_uses'],
                created_by=row['created_by'],
                description=row['description'],
                is_active=bool(row['is_active']),
                metadata=metadata
            )
            
        except Exception as e:
            logger.error("Failed to get invitation code: %s", e)
            return None
    
    def validate_code(self, code: str) -> bool:
        """
        验证邀请码是否有效
        
        Args:
            code: 邀请码
            
        Returns:
            邀请码是否有效
        """
        invitation_code = self.get_code(code)
        if invitation_code is None:
            return False
        
        return invitation_code.is_valid
    
    def use_code(
        self,
        code: str,
        used_by: Optional[str] = None,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> Optional[InvitationCode]:
        """
        使用邀请码
        
        Args:
            code: 邀请码
            used_by: 使用者
            user_agent: 用户代理
            ip_address: IP地址
            
        Returns:
            更新后的邀请码，如果无法使用则返回None
        """
        try:
            invitation_code = self.get_code(code)
            if invitation_code is None:
                logger.warning("Invitation code not found: %s", code)
                return None
            
            if not invitation_code.can_be_used():
                logger.warning("Invitation code cannot be used: %s (expired=%s, used_up=%s)", 
                             code, invitation_code.is_expired, invitation_code.is_used_up)
                return None
            
            # 更新使用次数
            invitation_code.current_uses += 1
            
            # 如果是单次使用，标记为非活跃
            if invitation_code.code_type == InvitationCodeType.SINGLE_USE:
                invitation_code.is_active = False
            
            # 更新数据库
            conn = self._get_conn()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE invitation_codes 
                SET current_uses = ?, is_active = ?
                WHERE code = ?
            ''', (invitation_code.current_uses, invitation_code.is_active, code))
            
            # 记录使用历史
            cursor.execute('''
                INSERT INTO invitation_code_usage 
                (code, used_at, used_by, user_agent, ip_address)
                VALUES (?, ?, ?, ?, ?)
            ''', (code, time.time(), used_by, user_agent, ip_address))
            
            conn.commit()
            
            logger.info("Used invitation code: %s by %s", code, used_by)
            return invitation_code
            
        except Exception as e:
            logger.error("Failed to use invitation code: %s", e)
            return None
    
    def revoke_code(self, code: str) -> bool:
        """
        撤销邀请码
        
        Args:
            code: 邀请码
            
        Returns:
            是否成功撤销
        """
        try:
            invitation_code = self.get_code(code)
            if invitation_code is None:
                logger.warning("Invitation code not found: %s", code)
                return False
            
            # 标记为非活跃
            invitation_code.is_active = False
            
            # 更新数据库
            conn = self._get_conn()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE invitation_codes 
                SET is_active = ?
                WHERE code = ?
            ''', (False, code))
            
            conn.commit()
            
            logger.info("Revoked invitation code: %s", code)
            return True
            
        except Exception as e:
            logger.error("Failed to revoke invitation code: %s", e)
            return False
    
    def list_codes(
        self,
        include_expired: bool = False,
        include_inactive: bool = False,
        limit: int = 100,
        offset: int = 0
    ) -> List[InvitationCode]:
        """
        列出邀请码
        
        Args:
            include_expired: 是否包含过期的
            include_inactive: 是否包含非活跃的
            limit: 返回数量限制
            offset: 偏移量
            
        Returns:
            邀请码列表
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            query = "SELECT * FROM invitation_codes WHERE 1=1"
            params = []
            
            if not include_expired:
                query += " AND (expires_at IS NULL OR expires_at > ?)"
                params.append(time.time())
            
            if not include_inactive:
                query += " AND is_active = 1"
            
            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            codes = []
            for row in rows:
                metadata = None
                if row['metadata']:
                    try:
                        import ast
                        metadata = ast.literal_eval(row['metadata'])
                    except:
                        metadata = None
                
                codes.append(InvitationCode(
                    code=row['code'],
                    code_type=InvitationCodeType(row['code_type']),
                    created_at=row['created_at'],
                    expires_at=row['expires_at'],
                    max_uses=row['max_uses'],
                    current_uses=row['current_uses'],
                    created_by=row['created_by'],
                    description=row['description'],
                    is_active=bool(row['is_active']),
                    metadata=metadata
                ))
            
            return codes
            
        except Exception as e:
            logger.error("Failed to list invitation codes: %s", e)
            return []
    
    def get_usage_history(self, code: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取邀请码使用历史
        
        Args:
            code: 邀请码
            limit: 返回数量限制
            
        Returns:
            使用历史列表
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM invitation_code_usage 
                WHERE code = ? 
                ORDER BY used_at DESC 
                LIMIT ?
            ''', (code, limit))
            
            rows = cursor.fetchall()
            
            history = []
            for row in rows:
                history.append({
                    "id": row['id'],
                    "code": row['code'],
                    "used_at": row['used_at'],
                    "used_by": row['used_by'],
                    "user_agent": row['user_agent'],
                    "ip_address": row['ip_address']
                })
            
            return history
            
        except Exception as e:
            logger.error("Failed to get usage history: %s", e)
            return []
    
    def cleanup_expired_codes(self) -> int:
        """
        清理过期的邀请码
        
        Returns:
            清理的数量
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            # 将过期的邀请码标记为非活跃
            cursor.execute('''
                UPDATE invitation_codes 
                SET is_active = 0 
                WHERE expires_at IS NOT NULL 
                AND expires_at < ? 
                AND is_active = 1
            ''', (time.time(),))
            
            cleaned = cursor.rowcount
            conn.commit()
            
            if cleaned > 0:
                logger.info("Cleaned up %d expired invitation codes", cleaned)
            
            return cleaned
            
        except Exception as e:
            logger.error("Failed to cleanup expired codes: %s", e)
            return 0
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取邀请码统计信息
        
        Returns:
            统计信息字典
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            # 总邀请码数
            cursor.execute("SELECT COUNT(*) FROM invitation_codes")
            total_codes = cursor.fetchone()[0]
            
            # 活跃邀请码数
            cursor.execute("SELECT COUNT(*) FROM invitation_codes WHERE is_active = 1")
            active_codes = cursor.fetchone()[0]
            
            # 过期邀请码数
            cursor.execute('''
                SELECT COUNT(*) FROM invitation_codes 
                WHERE expires_at IS NOT NULL AND expires_at < ?
            ''', (time.time(),))
            expired_codes = cursor.fetchone()[0]
            
            # 已使用邀请码数
            cursor.execute("SELECT COUNT(*) FROM invitation_codes WHERE current_uses > 0")
            used_codes = cursor.fetchone()[0]
            
            # 总使用次数
            cursor.execute("SELECT SUM(current_uses) FROM invitation_codes")
            total_uses = cursor.fetchone()[0] or 0
            
            # 按类型统计
            cursor.execute('''
                SELECT code_type, COUNT(*) 
                FROM invitation_codes 
                GROUP BY code_type
            ''')
            by_type = dict(cursor.fetchall())
            
            return {
                "total_codes": total_codes,
                "active_codes": active_codes,
                "expired_codes": expired_codes,
                "used_codes": used_codes,
                "total_uses": total_uses,
                "by_type": by_type
            }
            
        except Exception as e:
            logger.error("Failed to get statistics: %s", e)
            return {}


# 全局实例
_invitation_code_model: Optional[InvitationCodeModel] = None


def get_invitation_code_model() -> InvitationCodeModel:
    """
    获取邀请码管理器实例（单例模式）
    
    Returns:
        InvitationCodeModel实例
    """
    global _invitation_code_model
    if _invitation_code_model is None:
        _invitation_code_model = InvitationCodeModel()
    return _invitation_code_model


def reset_invitation_code_model():
    """
    重置邀请码管理器实例（用于测试）
    """
    global _invitation_code_model
    if _invitation_code_model is not None:
        # 关闭数据库连接
        if _invitation_code_model._conn:
            _invitation_code_model._conn.close()
        _invitation_code_model = None