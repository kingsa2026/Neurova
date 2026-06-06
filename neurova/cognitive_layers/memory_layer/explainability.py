"""
可解释性模块 - 提供触发链追溯功能

功能:
- 记录记忆操作的触发链
- 追溯记忆召回的原因
- 解释为什么某个记忆被记住或召回
- 提供触发链可视化
"""

import collections
import datetime
import json
import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class NodeType(str, Enum):
    """节点类型"""
    INPUT = "input"  # 输入节点
    PROCESSING = "processing"  # 处理节点
    DECISION = "decision"  # 决策节点
    OUTPUT = "output"  # 输出节点
    MEMORY = "memory"  # 记忆节点
    TRIGGER = "trigger"  # 触发节点


@dataclass
class TriggerNode:
    """触发链节点"""
    node_id: str
    node_type: NodeType
    name: str
    description: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    parent_id: Optional[str] = None
    children: List[str] = field(default_factory=list)
    
    def add_child(self, child_id: str) -> None:
        """添加子节点"""
        if child_id not in self.children:
            self.children.append(child_id)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "name": self.name,
            "description": self.description,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "parent_id": self.parent_id,
            "children": self.children,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TriggerNode":
        """从字典创建"""
        return cls(
            node_id=data.get("node_id", ""),
            node_type=NodeType(data.get("node_type", "input")),
            name=data.get("name", ""),
            description=data.get("description", ""),
            data=data.get("data", {}),
            timestamp=datetime.datetime.fromisoformat(data.get("timestamp", datetime.datetime.now(datetime.timezone.utc).isoformat())),
            parent_id=data.get("parent_id"),
            children=data.get("children", []),
        )


@dataclass
class TriggerChain:
    """触发链"""
    chain_id: str
    name: str
    description: str = ""
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    completed_at: Optional[datetime.datetime] = None
    nodes: Dict[str, TriggerNode] = field(default_factory=dict)
    root_node_id: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_node(self, node: TriggerNode) -> None:
        """添加节点"""
        self.nodes[node.node_id] = node
        
        # 如果是第一个节点，设为根节点
        if self.root_node_id is None:
            self.root_node_id = node.node_id
        
        # 如果有父节点，建立父子关系
        if node.parent_id and node.parent_id in self.nodes:
            parent = self.nodes[node.parent_id]
            parent.add_child(node.node_id)
    
    def set_result(self, result: Dict[str, Any]) -> None:
        """设置结果"""
        self.result = result
        self.completed_at = datetime.datetime.now(datetime.timezone.utc)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "chain_id": self.chain_id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "nodes": {node_id: node.to_dict() for node_id, node in self.nodes.items()},
            "root_node_id": self.root_node_id,
            "result": self.result,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TriggerChain":
        """从字典创建"""
        chain = cls(
            chain_id=data.get("chain_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            created_at=datetime.datetime.fromisoformat(data.get("created_at", datetime.datetime.now(datetime.timezone.utc).isoformat())),
            metadata=data.get("metadata", {}),
        )
        
        # 设置完成时间
        if data.get("completed_at"):
            chain.completed_at = datetime.datetime.fromisoformat(data["completed_at"])
        
        # 设置结果
        chain.result = data.get("result")
        chain.root_node_id = data.get("root_node_id")
        
        # 创建节点
        for node_id, node_data in data.get("nodes", {}).items():
            node = TriggerNode.from_dict(node_data)
            chain.nodes[node_id] = node
        
        return chain


class ExplainabilityManager:
    """
    可解释性管理器
    
    提供触发链追溯功能，支持：
    1. 记录记忆操作的触发链
    2. 追溯记忆召回的原因
    3. 解释为什么某个记忆被记住或召回
    4. 提供触发链可视化
    """
    
    def __init__(
        self,
        storage: Any = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化可解释性管理器
        
        Args:
            storage: 存储后端
            config: 配置字典
        """
        self._storage = storage
        self._config = config or {}
        self._lock = threading.RLock()
        
        # 触发链存储
        self._chains: Dict[str, TriggerChain] = {}
        self._memory_chains: Dict[str, List[str]] = defaultdict(list)  # memory_id -> chain_ids
        
        # 统计
        self._total_chains = 0
        self._total_nodes = 0
        
        # 配置
        self._max_chains = self._config.get("max_chains", 10000)
        self._max_chain_age_days = self._config.get("max_chain_age_days", 30)
        
        logger.info("ExplainabilityManager initialized")
    
    def start_chain(
        self,
        name: str,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        开始新的触发链
        
        Args:
            name: 链名称
            description: 描述
            metadata: 元数据
            
        Returns:
            链ID
        """
        with self._lock:
            chain_id = str(uuid.uuid4())
            
            chain = TriggerChain(
                chain_id=chain_id,
                name=name,
                description=description,
                metadata=metadata or {},
            )
            
            self._chains[chain_id] = chain
            self._total_chains += 1
            
            # 清理旧链
            self._cleanup_old_chains()
            
            logger.debug(f"Trigger chain started: {chain_id} ({name})")
            return chain_id
    
    def add_node_to_chain(
        self,
        chain_id: str,
        node_type: NodeType,
        name: str,
        description: str = "",
        data: Optional[Dict[str, Any]] = None,
        parent_node_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        向触发链添加节点
        
        Args:
            chain_id: 链ID
            node_type: 节点类型
            name: 节点名称
            description: 描述
            data: 数据
            parent_node_id: 父节点ID
            
        Returns:
            节点ID，如果失败返回None
        """
        with self._lock:
            chain = self._chains.get(chain_id)
            if not chain:
                logger.warning(f"Chain not found: {chain_id}")
                return None
            
            # 生成节点ID
            node_id = str(uuid.uuid4())
            
            # 确定父节点
            if parent_node_id is None and chain.nodes:
                # 默认使用最后一个节点作为父节点
                last_node_id = None
                for nid, node in chain.nodes.items():
                    if not node.children:  # 叶子节点
                        last_node_id = nid
                        break
                parent_node_id = last_node_id
            
            # 创建节点
            node = TriggerNode(
                node_id=node_id,
                node_type=node_type,
                name=name,
                description=description,
                data=data or {},
                parent_id=parent_node_id,
            )
            
            # 添加到链
            chain.add_node(node)
            self._total_nodes += 1
            
            logger.debug(f"Node added to chain {chain_id}: {node_id} ({name})")
            return node_id
    
    def complete_chain(
        self,
        chain_id: str,
        result: Optional[Dict[str, Any]] = None,
        memory_id: Optional[str] = None,
    ) -> bool:
        """
        完成触发链
        
        Args:
            chain_id: 链ID
            result: 结果
            memory_id: 关联的记忆ID
            
        Returns:
            是否完成成功
        """
        with self._lock:
            chain = self._chains.get(chain_id)
            if not chain:
                logger.warning(f"Chain not found: {chain_id}")
                return False
            
            # 设置结果
            chain.set_result(result or {})
            
            # 关联记忆
            if memory_id:
                self._memory_chains[memory_id].append(chain_id)
            
            logger.debug(f"Chain completed: {chain_id}")
            return True
    
    def get_chain(self, chain_id: str) -> Optional[TriggerChain]:
        """
        获取触发链
        
        Args:
            chain_id: 链ID
            
        Returns:
            触发链对象，如果不存在返回None
        """
        return self._chains.get(chain_id)
    
    def get_memory_chains(self, memory_id: str) -> List[TriggerChain]:
        """
        获取记忆的所有触发链
        
        Args:
            memory_id: 记忆ID
            
        Returns:
            触发链列表
        """
        chain_ids = self._memory_chains.get(memory_id, [])
        chains = []
        
        for chain_id in chain_ids:
            chain = self._chains.get(chain_id)
            if chain:
                chains.append(chain)
        
        return chains
    
    def explain_memory(self, memory_id: str) -> Dict[str, Any]:
        """
        解释记忆
        
        Args:
            memory_id: 记忆ID
            
        Returns:
            解释信息字典
        """
        chains = self.get_memory_chains(memory_id)
        
        if not chains:
            return {
                "memory_id": memory_id,
                "explanation": "No trigger chains found for this memory",
                "chains": [],
            }
        
        # 构建解释
        explanations = []
        for chain in chains:
            chain_explanation = {
                "chain_id": chain.chain_id,
                "name": chain.name,
                "description": chain.description,
                "created_at": chain.created_at.isoformat(),
                "completed_at": chain.completed_at.isoformat() if chain.completed_at else None,
                "node_count": len(chain.nodes),
                "result": chain.result,
            }
            
            # 构建节点路径
            if chain.root_node_id:
                path = self._build_node_path(chain, chain.root_node_id)
                chain_explanation["path"] = path
            
            explanations.append(chain_explanation)
        
        return {
            "memory_id": memory_id,
            "explanation": f"Memory has {len(chains)} trigger chain(s)",
            "chains": explanations,
        }
    
    def _build_node_path(self, chain: TriggerChain, node_id: str) -> List[Dict[str, Any]]:
        """
        构建节点路径
        
        Args:
            chain: 触发链
            node_id: 起始节点ID
            
        Returns:
            节点路径列表
        """
        path = []
        current_id = node_id
        visited = set()
        
        while current_id and current_id not in visited:
            visited.add(current_id)
            node = chain.nodes.get(current_id)
            
            if node:
                path.append({
                    "node_id": node.node_id,
                    "node_type": node.node_type.value,
                    "name": node.name,
                    "description": node.description,
                    "timestamp": node.timestamp.isoformat(),
                })
                
                # 移动到第一个子节点
                if node.children:
                    current_id = node.children[0]
                else:
                    current_id = None
            else:
                break
        
        return path
    
    def visualize_chain(self, chain_id: str) -> str:
        """
        可视化触发链
        
        Args:
            chain_id: 链ID
            
        Returns:
            可视化文本
        """
        chain = self._chains.get(chain_id)
        if not chain:
            return f"Chain not found: {chain_id}"
        
        lines = []
        lines.append(f"Trigger Chain: {chain.name}")
        lines.append(f"ID: {chain.chain_id}")
        lines.append(f"Description: {chain.description}")
        lines.append(f"Created: {chain.created_at.isoformat()}")
        if chain.completed_at:
            lines.append(f"Completed: {chain.completed_at.isoformat()}")
        lines.append("")
        
        # 递归打印节点
        if chain.root_node_id:
            self._visualize_node(chain, chain.root_node_id, lines, indent=0)
        
        # 打印结果
        if chain.result:
            lines.append("")
            lines.append("Result:")
            lines.append(json.dumps(chain.result, indent=2, ensure_ascii=False))
        
        return "\n".join(lines)
    
    def _visualize_node(
        self,
        chain: TriggerChain,
        node_id: str,
        lines: List[str],
        indent: int = 0,
    ) -> None:
        """
        递归可视化节点
        
        Args:
            chain: 触发链
            node_id: 节点ID
            lines: 输出行列表
            indent: 缩进级别
        """
        node = chain.nodes.get(node_id)
        if not node:
            return
        
        # 打印当前节点
        prefix = "  " * indent
        type_symbol = {
            NodeType.INPUT: "📥",
            NodeType.PROCESSING: "⚙️",
            NodeType.DECISION: "🔀",
            NodeType.OUTPUT: "📤",
            NodeType.MEMORY: "🧠",
            NodeType.TRIGGER: "⚡",
        }.get(node.node_type, "❓")
        
        lines.append(f"{prefix}{type_symbol} {node.name}")
        if node.description:
            lines.append(f"{prefix}   {node.description}")
        
        # 递归打印子节点
        for child_id in node.children:
            self._visualize_node(chain, child_id, lines, indent + 1)
    
    def _cleanup_old_chains(self) -> None:
        """清理旧触发链"""
        if len(self._chains) <= self._max_chains:
            return
        
        # 按时间排序
        sorted_chains = sorted(
            self._chains.items(),
            key=lambda x: x[1].created_at,
        )
        
        # 删除最旧的链
        to_remove = len(self._chains) - self._max_chains
        for i in range(to_remove):
            chain_id, chain = sorted_chains[i]
            
            # 从记忆关联中移除
            for memory_id, chain_ids in self._memory_chains.items():
                if chain_id in chain_ids:
                    chain_ids.remove(chain_id)
            
            # 删除链
            del self._chains[chain_id]
        
        logger.debug(f"Cleaned up {to_remove} old trigger chains")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            统计信息字典
        """
        with self._lock:
            return {
                "total_chains": self._total_chains,
                "active_chains": len(self._chains),
                "total_nodes": self._total_nodes,
                "memory_associations": len(self._memory_chains),
                "max_chains": self._max_chains,
                "max_chain_age_days": self._max_chain_age_days,
            }
    
    def export_chain(self, chain_id: str) -> Optional[str]:
        """
        导出触发链为JSON
        
        Args:
            chain_id: 链ID
            
        Returns:
            JSON字符串，如果失败返回None
        """
        chain = self._chains.get(chain_id)
        if not chain:
            return None
        
        try:
            return json.dumps(chain.to_dict(), indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to export chain: {e}")
            return None
    
    def import_chain(self, json_str: str) -> Optional[str]:
        """
        从JSON导入触发链
        
        Args:
            json_str: JSON字符串
            
        Returns:
            链ID，如果失败返回None
        """
        try:
            data = json.loads(json_str)
            chain = TriggerChain.from_dict(data)
            
            with self._lock:
                self._chains[chain.chain_id] = chain
                self._total_chains += 1
                
                # 如果有记忆关联
                if chain.result and "memory_id" in chain.result:
                    memory_id = chain.result["memory_id"]
                    self._memory_chains[memory_id].append(chain.chain_id)
            
            logger.info(f"Chain imported: {chain.chain_id}")
            return chain.chain_id
            
        except Exception as e:
            logger.error(f"Failed to import chain: {e}")
            return None


# 全局单例
_explainability_manager: Optional[ExplainabilityManager] = None
_manager_lock = threading.Lock()


def get_explainability_manager(
    storage: Any = None,
    config: Optional[Dict[str, Any]] = None,
) -> ExplainabilityManager:
    """
    获取全局可解释性管理器单例
    
    Args:
        storage: 存储后端
        config: 配置字典
        
    Returns:
        ExplainabilityManager实例
    """
    global _explainability_manager
    if _explainability_manager is None:
        with _manager_lock:
            if _explainability_manager is None:
                _explainability_manager = ExplainabilityManager(
                    storage=storage,
                    config=config,
                )
    return _explainability_manager


def reset_explainability_manager() -> None:
    """重置全局可解释性管理器（用于测试）"""
    global _explainability_manager
    with _manager_lock:
        _explainability_manager = None