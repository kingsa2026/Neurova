"""
Neurflow 团队 Agent 管理器 — 垂直切片 9

提供临时团队 Agent 的创建、归档和恢复功能。
支持工作流中创建专用 Agent，执行完成后归档以保留上下文。

架构特点：
- 线程安全：使用 RLock 保护共享状态
- 单例模式：通过 get_agent_manager() 获取全局实例
- 三层隔离：支持按 flow_id 隔离 Agent
- 延迟加载：避免循环导入
"""
import threading
import time
import uuid
from typing import Dict, List, Optional, Any

from .models import AgentInfo


class NeurflowAgentManager:
    """团队 Agent 管理器 — 支持临时创建和归档
    
    使用示例：
        manager = get_agent_manager()
        
        # 创建临时团队 Agent
        agent = manager.create_agent(
            name="编码助手",
            role="coder",
            config={"model": "gpt-4", "temperature": 0.7},
            flow_id="workflow_123"
        )
        
        # 在工作流中使用 Agent
        agent_id = agent.agent_id
        
        # 工作流完成后归档 Agent
        manager.archive_agent(agent_id)
        
        # 需要时可以恢复
        manager.restore_agent(agent_id)
    """
    
    def __init__(self):
        """初始化 Agent 管理器"""
        self._agents: Dict[str, AgentInfo] = {}
        self._archived: Dict[str, AgentInfo] = {}
        self._lock = threading.RLock()
    
    def create_agent(self, name: str, role: str,
                     config: Optional[Dict[str, Any]] = None,
                     flow_id: Optional[str] = None) -> AgentInfo:
        """创建临时团队 Agent
        
        Args:
            name: Agent 名称
            role: Agent 角色（如 "coder", "reviewer", "assistant"）
            config: Agent 配置参数（可选）
            flow_id: 关联的工作流 ID（可选）
            
        Returns:
            新创建的 AgentInfo 实例
        """
        agent_id = f"neurflow_{uuid.uuid4().hex[:8]}"
        agent = AgentInfo(
            agent_id=agent_id,
            name=name,
            role=role,
            config=config or {},
            flow_id=flow_id,
            created_at=time.time(),
            status="active",
        )
        
        with self._lock:
            self._agents[agent_id] = agent
        
        return agent
    
    def get_agent(self, agent_id: str) -> Optional[AgentInfo]:
        """获取 Agent 信息
        
        Args:
            agent_id: Agent ID
            
        Returns:
            AgentInfo 实例，如果不存在返回 None
        """
        with self._lock:
            # 先在活跃 Agent 中查找
            if agent_id in self._agents:
                return self._agents[agent_id]
            
            # 再在归档 Agent 中查找
            if agent_id in self._archived:
                return self._archived[agent_id]
            
            return None
    
    def list_agents(self, flow_id: Optional[str] = None,
                    include_archived: bool = False) -> List[AgentInfo]:
        """列出 Agent
        
        Args:
            flow_id: 按工作流 ID 过滤（可选）
            include_archived: 是否包含归档的 Agent
            
        Returns:
            AgentInfo 列表
        """
        with self._lock:
            # 合并活跃和归档的 Agent
            pool = {**self._agents}
            
            if include_archived:
                pool.update(self._archived)
            
            # 按 flow_id 过滤
            if flow_id:
                pool = {k: v for k, v in pool.items() if v.flow_id == flow_id}
            
            return list(pool.values())
    
    def archive_agent(self, agent_id: str) -> bool:
        """归档 Agent
        
        Args:
            agent_id: Agent ID
            
        Returns:
            是否成功归档
        """
        with self._lock:
            # 从活跃 Agent 中移除
            agent = self._agents.pop(agent_id, None)
            
            if not agent:
                # 如果不在活跃列表中，可能已归档或不存在
                return False
            
            # 更新状态
            agent.status = "archived"
            agent.archived_at = time.time()
            
            # 移动到归档列表
            self._archived[agent_id] = agent
            
            return True
    
    def restore_agent(self, agent_id: str) -> bool:
        """恢复归档的 Agent
        
        Args:
            agent_id: Agent ID
            
        Returns:
            是否成功恢复
        """
        with self._lock:
            # 从归档 Agent 中移除
            agent = self._archived.pop(agent_id, None)
            
            if not agent:
                # 如果不在归档列表中，可能未归档或不存在
                return False
            
            # 更新状态
            agent.status = "active"
            agent.archived_at = None
            
            # 移回活跃列表
            self._agents[agent_id] = agent
            
            return True
    
    def delete_agent(self, agent_id: str) -> bool:
        """删除 Agent
        
        Args:
            agent_id: Agent ID
            
        Returns:
            是否成功删除
        """
        with self._lock:
            # 尝试从活跃列表删除
            if self._agents.pop(agent_id, None):
                return True
            
            # 尝试从归档列表删除
            if self._archived.pop(agent_id, None):
                return True
            
            # Agent 不存在
            return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息
        
        Returns:
            包含统计信息的字典
        """
        with self._lock:
            return {
                "active_count": len(self._agents),
                "archived_count": len(self._archived),
                "total_count": len(self._agents) + len(self._archived),
                "by_flow_id": self._count_by_flow_id(),
            }
    
    def _count_by_flow_id(self) -> Dict[str, int]:
        """按 flow_id 统计 Agent 数量"""
        counts: Dict[str, int] = {}
        
        # 统计活跃 Agent
        for agent in self._agents.values():
            flow_id = agent.flow_id or "unassigned"
            counts[flow_id] = counts.get(flow_id, 0) + 1
        
        # 统计归档 Agent
        for agent in self._archived.values():
            flow_id = agent.flow_id or "unassigned"
            counts[flow_id] = counts.get(flow_id, 0) + 1
        
        return counts


# 单例管理
_agent_manager_instance: Optional[NeurflowAgentManager] = None
_agent_manager_lock = threading.Lock()


def get_agent_manager() -> NeurflowAgentManager:
    """获取 Agent 管理器单例
    
    Returns:
        NeurflowAgentManager 实例
    """
    global _agent_manager_instance
    
    # 双重检查锁定
    if _agent_manager_instance is None:
        with _agent_manager_lock:
            if _agent_manager_instance is None:
                _agent_manager_instance = NeurflowAgentManager()
    
    return _agent_manager_instance


def reset_agent_manager() -> None:
    """重置 Agent 管理器单例
    
    主要用于测试，清除所有 Agent 状态。
    """
    global _agent_manager_instance
    
    with _agent_manager_lock:
        _agent_manager_instance = None


# 便捷导出
__all__ = [
    "NeurflowAgentManager",
    "get_agent_manager",
    "reset_agent_manager",
]