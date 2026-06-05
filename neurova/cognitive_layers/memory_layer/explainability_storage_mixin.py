"""
Explainability Storage Mixin - 触发链存储功能

提供触发链的保存、查询和删除功能。
"""

import datetime
import json
import logging
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ExplainabilityStorageMixin:
    """
    可解释性存储 Mixin
    
    提供触发链的保存、查询和删除功能。
    """
    
    def __init__(self):
        """初始化触发链存储"""
        self._trigger_chains: Dict[str, Dict[str, Any]] = {}
        logger.info("ExplainabilityStorageMixin 初始化完成")
    
    def save_trigger_chain(
        self,
        memory_id: str,
        chain_type: str,
        steps: List[Dict[str, Any]],
        confidence: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        保存触发链
        
        Args:
            memory_id: 关联的记忆ID
            chain_type: 触发链类型
            steps: 触发步骤列表
            confidence: 置信度
            metadata: 可选的元数据
            
        Returns:
            保存的触发链
        """
        chain_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc)
        
        chain = {
            "id": chain_id,
            "memory_id": memory_id,
            "chain_type": chain_type,
            "steps": steps,
            "confidence": confidence,
            "metadata": metadata or {},
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "step_count": len(steps),
        }
        
        self._trigger_chains[chain_id] = chain
        logger.debug(f"保存触发链: {chain_id} (记忆: {memory_id})")
        
        return chain
    
    def get_trigger_chain(self, chain_id: str) -> Optional[Dict[str, Any]]:
        """
        获取触发链
        
        Args:
            chain_id: 触发链ID
            
        Returns:
            触发链，如果不存在返回None
        """
        return self._trigger_chains.get(chain_id)
    
    def get_trigger_chains_by_memory(self, memory_id: str) -> List[Dict[str, Any]]:
        """
        获取记忆的所有触发链
        
        Args:
            memory_id: 记忆ID
            
        Returns:
            触发链列表
        """
        results = []
        for chain in self._trigger_chains.values():
            if chain["memory_id"] == memory_id:
                results.append(chain)
        
        # 按创建时间排序
        results.sort(key=lambda x: x["created_at"], reverse=True)
        return results
    
    def get_trigger_chains_by_type(self, chain_type: str) -> List[Dict[str, Any]]:
        """
        获取特定类型的触发链
        
        Args:
            chain_type: 触发链类型
            
        Returns:
            触发链列表
        """
        results = []
        for chain in self._trigger_chains.values():
            if chain["chain_type"] == chain_type:
                results.append(chain)
        
        results.sort(key=lambda x: x["created_at"], reverse=True)
        return results
    
    def update_trigger_chain(
        self,
        chain_id: str,
        steps: Optional[List[Dict[str, Any]]] = None,
        confidence: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        更新触发链
        
        Args:
            chain_id: 触发链ID
            steps: 新步骤列表
            confidence: 新置信度
            metadata: 新元数据
            
        Returns:
            更新后的触发链
        """
        chain = self._trigger_chains.get(chain_id)
        if not chain:
            return None
        
        if steps is not None:
            chain["steps"] = steps
            chain["step_count"] = len(steps)
        if confidence is not None:
            chain["confidence"] = confidence
        if metadata is not None:
            chain["metadata"] = metadata
        
        chain["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        return chain
    
    def delete_trigger_chain(self, chain_id: str) -> bool:
        """
        删除触发链
        
        Args:
            chain_id: 触发链ID
            
        Returns:
            是否删除成功
        """
        if chain_id in self._trigger_chains:
            del self._trigger_chains[chain_id]
            logger.debug(f"删除触发链: {chain_id}")
            return True
        return False
    
    def delete_trigger_chains_by_memory(self, memory_id: str) -> int:
        """
        删除记忆的所有触发链
        
        Args:
            memory_id: 记忆ID
            
        Returns:
            删除的触发链数量
        """
        to_delete = []
        for chain_id, chain in self._trigger_chains.items():
            if chain["memory_id"] == memory_id:
                to_delete.append(chain_id)
        
        for chain_id in to_delete:
            del self._trigger_chains[chain_id]
        
        if to_delete:
            logger.debug(f"删除记忆 {memory_id} 的 {len(to_delete)} 个触发链")
        
        return len(to_delete)
    
    def search_trigger_chains(
        self,
        query: str,
        chain_type: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        搜索触发链
        
        Args:
            query: 搜索查询
            chain_type: 可选的类型过滤
            limit: 返回数量限制
            
        Returns:
            匹配的触发链
        """
        query_lower = query.lower()
        results = []
        
        for chain in self._trigger_chains.values():
            # 按类型过滤
            if chain_type and chain["chain_type"] != chain_type:
                continue
            
            # 在步骤中搜索
            found = False
            for step in chain["steps"]:
                # 搜索步骤描述
                if isinstance(step, dict):
                    for value in step.values():
                        if isinstance(value, str) and query_lower in value.lower():
                            found = True
                            break
                if found:
                    break
            
            if found:
                results.append(chain)
        
        # 按置信度排序
        results.sort(key=lambda x: x["confidence"], reverse=True)
        
        return results[:limit]
    
    def get_trigger_chain_statistics(self) -> Dict[str, Any]:
        """
        获取触发链统计信息
        
        Returns:
            统计信息字典
        """
        chains = list(self._trigger_chains.values())
        
        if not chains:
            return {
                "total_chains": 0,
                "type_distribution": {},
                "average_steps": 0,
                "average_confidence": 0,
                "most_connected_memories": [],
            }
        
        # 类型分布
        type_dist: Dict[str, int] = {}
        for chain in chains:
            ct = chain["chain_type"]
            type_dist[ct] = type_dist.get(ct, 0) + 1
        
        # 平均步骤数
        total_steps = sum(chain["step_count"] for chain in chains)
        avg_steps = total_steps / len(chains)
        
        # 平均置信度
        total_confidence = sum(chain["confidence"] for chain in chains)
        avg_confidence = total_confidence / len(chains)
        
        # 最常连接的记忆
        memory_count: Dict[str, int] = {}
        for chain in chains:
            mid = chain["memory_id"]
            memory_count[mid] = memory_count.get(mid, 0) + 1
        
        most_connected = sorted(memory_count.items(), key=lambda x: x[1], reverse=True)[:5]
        
        return {
            "total_chains": len(chains),
            "type_distribution": type_dist,
            "average_steps": avg_steps,
            "average_confidence": avg_confidence,
            "most_connected_memories": most_connected,
        }
    
    def clear_trigger_chains(self) -> int:
        """
        清空所有触发链
        
        Returns:
            删除的触发链数量
        """
        count = len(self._trigger_chains)
        self._trigger_chains.clear()
        logger.debug(f"清空触发链: {count} 个")
        return count