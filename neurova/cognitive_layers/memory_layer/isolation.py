"""
三层隔离上下文

提供统一的隔离机制，支持：
1. Agent隔离 (agent_id) - 不同Agent的记忆完全隔离
2. 系统用户隔离 (neuser_id) - 同一Agent下不同系统用户的记忆隔离
3. 对话用户隔离 (user_id) - 同一系统用户下不同对话的记忆隔离

设计原则：
- 深度模块：小接口，深实现
- 单一职责：只负责隔离上下文管理
- 不可变性：创建后不可修改
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class IsolationContext:
    """
    三层隔离上下文
    
    使用方式：
        # 创建隔离上下文
        ctx = IsolationContext(agent_id="agent_1", user_id="user_1")
        
        # 用于存储层
        storage.save(content="...", isolation_context=ctx)
        
        # 用于睡眠整合
        sleep.consolidate(records, isolation_context=ctx)
        
        # 用于模型层
        memory = Memory(content="...", isolation_context=ctx)
    
    属性：
        agent_id: Agent ID（第1层隔离）
        neuser_id: 系统用户ID（第2层隔离）
        user_id: 对话用户ID（第3层隔离）
        key: 唯一标识符，格式为 "{agent_id}:{neuser_id}:{user_id}"
    """
    
    agent_id: str = "default"
    neuser_id: str = "default"
    user_id: str = "default"
    shared: bool = False  # 跨 agent 共享开关
    
    @property
    def key(self) -> str:
        """唯一标识符，用于单例管理和索引"""
        return f"{self.agent_id}:{self.neuser_id}:{self.user_id}"
    
    def with_agent(self, agent_id: str) -> IsolationContext:
        """创建新的隔离上下文，只修改agent_id"""
        return IsolationContext(
            agent_id=agent_id,
            neuser_id=self.neuser_id,
            user_id=self.user_id,
            shared=self.shared
        )
    
    def with_neuser(self, neuser_id: str) -> IsolationContext:
        """创建新的隔离上下文，只修改neuser_id"""
        return IsolationContext(
            agent_id=self.agent_id,
            neuser_id=neuser_id,
            user_id=self.user_id,
            shared=self.shared
        )
    
    def with_user(self, user_id: str) -> IsolationContext:
        """创建新的隔离上下文，只修改user_id"""
        return IsolationContext(
            agent_id=self.agent_id,
            neuser_id=self.neuser_id,
            user_id=user_id,
            shared=self.shared
        )
    
    def with_shared(self, shared: bool = True) -> IsolationContext:
        """创建新的隔离上下文，修改共享开关"""
        return IsolationContext(
            agent_id=self.agent_id,
            neuser_id=self.neuser_id,
            user_id=self.user_id,
            shared=shared
        )
    
    def to_dict(self) -> dict:
        """转换为字典格式"""
        result = {
            "agent_id": self.agent_id,
            "neuser_id": self.neuser_id,
            "user_id": self.user_id
        }
        if self.shared:
            result["shared"] = True
        return result
    
    @classmethod
    def from_dict(cls, data: dict) -> IsolationContext:
        """从字典创建隔离上下文"""
        return cls(
            agent_id=data.get("agent_id", "default"),
            neuser_id=data.get("neuser_id", "default"),
            user_id=data.get("user_id", "default"),
            shared=data.get("shared", False)
        )
    
    @classmethod
    def from_legacy(cls, owner: Optional[str] = None, 
                    agent_id: Optional[str] = None,
                    user_id: Optional[str] = None,
                    shared: bool = False) -> IsolationContext:
        """
        从旧版字段创建隔离上下文（兼容性方法）
        
        Args:
            owner: 旧版owner字段（storage.py）
            agent_id: 旧版agent_id字段（models.py）
            user_id: 旧版user_id字段（models.py）
            shared: 是否跨agent共享
        
        Returns:
            IsolationContext实例
        """
        # 优先使用agent_id，其次使用owner作为agent_id
        final_agent_id = agent_id or owner or "default"
        final_user_id = user_id or "default"
        
        return cls(
            agent_id=final_agent_id,
            neuser_id="default",  # 旧版没有neuser_id
            user_id=final_user_id,
            shared=shared
        )
    
    def __str__(self) -> str:
        return f"IsolationContext(agent={self.agent_id}, neuser={self.neuser_id}, user={self.user_id})"
    
    def __repr__(self) -> str:
        return self.__str__()


# 全局默认上下文
DEFAULT_ISOLATION = IsolationContext()


def get_default_isolation() -> IsolationContext:
    """获取默认隔离上下文"""
    return DEFAULT_ISOLATION


def create_isolation(agent_id: str = "default", 
                     neuser_id: str = "default",
                     user_id: str = "default",
                     shared: bool = False) -> IsolationContext:
    """创建隔离上下文的便捷函数"""
    return IsolationContext(
        agent_id=agent_id,
        neuser_id=neuser_id,
        user_id=user_id,
        shared=shared
    )
