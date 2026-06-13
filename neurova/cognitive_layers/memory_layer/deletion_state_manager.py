"""
删除状态维护器

管理实体的删除状态，支持临时删除、恢复和永久删除。
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DeletionRecord:
    """删除记录"""
    entity_id: str
    entity_type: str
    reason: str
    deleted_at: float = field(default_factory=time.time)
    is_permanent: bool = False
    restored_at: Optional[float] = None


class DeletionStateManager:
    """
    删除状态维护器
    
    管理实体的删除状态，支持：
    - 临时删除（可恢复）
    - 永久删除（不可恢复）
    - 批量清理旧的删除记录
    """
    
    def __init__(self):
        """初始化删除状态维护器"""
        self._deletions: Dict[str, DeletionRecord] = {}
        logger.info("DeletionStateManager 初始化完成")
    
    def mark_as_deleted(
        self,
        entity_id: str,
        entity_type: str,
        reason: str = "",
    ):
        """
        标记实体为已删除
        
        Args:
            entity_id: 实体ID
            entity_type: 实体类型
            reason: 删除原因
        """
        record = DeletionRecord(
            entity_id=entity_id,
            entity_type=entity_type,
            reason=reason,
        )
        self._deletions[entity_id] = record
        logger.debug("标记删除: %s (%s)", entity_id, entity_type)
    
    def get_deletion_status(self, entity_id: str) -> Dict[str, Any]:
        """
        获取实体的删除状态
        
        Args:
            entity_id: 实体ID
            
        Returns:
            删除状态字典
        """
        record = self._deletions.get(entity_id)
        
        if record is None:
            return {"is_deleted": False}
        
        return {
            "is_deleted": True,
            "is_permanent": record.is_permanent,
            "entity_type": record.entity_type,
            "reason": record.reason,
            "deleted_at": record.deleted_at,
            "restored_at": record.restored_at,
        }
    
    def restore_entity(self, entity_id: str) -> bool:
        """
        恢复已删除的实体
        
        Args:
            entity_id: 实体ID
            
        Returns:
            是否成功恢复
        """
        record = self._deletions.get(entity_id)
        
        if record is None:
            return False
        
        if record.is_permanent:
            logger.warning("无法恢复永久删除的实体: %s", entity_id)
            return False
        
        # 标记为已恢复
        record.restored_at = time.time()
        del self._deletions[entity_id]
        
        logger.debug("恢复实体: %s", entity_id)
        return True
    
    def permanently_delete(self, entity_id: str) -> bool:
        """
        永久删除实体
        
        Args:
            entity_id: 实体ID
            
        Returns:
            是否成功删除
        """
        record = self._deletions.get(entity_id)
        
        if record is None:
            return False
        
        record.is_permanent = True
        logger.debug("永久删除: %s", entity_id)
        return True
    
    def get_deleted_entities(
        self,
        entity_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取已删除实体列表
        
        Args:
            entity_type: 实体类型过滤（可选）
            
        Returns:
            已删除实体列表
        """
        result = []
        
        for entity_id, record in self._deletions.items():
            if entity_type and record.entity_type != entity_type:
                continue
            
            result.append({
                "entity_id": entity_id,
                "entity_type": record.entity_type,
                "reason": record.reason,
                "deleted_at": record.deleted_at,
                "is_permanent": record.is_permanent,
            })
        
        return result
    
    def cleanup_old_deleted(self, days: int = 30) -> int:
        """
        清理旧的已删除实体
        
        Args:
            days: 保留天数
            
        Returns:
            清理的实体数量
        """
        cutoff_time = time.time() - (days * 24 * 60 * 60)
        
        to_remove = []
        for entity_id, record in self._deletions.items():
            if record.deleted_at < cutoff_time:
                to_remove.append(entity_id)
        
        for entity_id in to_remove:
            del self._deletions[entity_id]
        
        if to_remove:
            logger.info("清理了 %d 个旧的删除记录", len(to_remove))
        
        return len(to_remove)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total = len(self._deletions)
        permanent = sum(1 for r in self._deletions.values() if r.is_permanent)
        
        return {
            "total_deleted": total,
            "permanent_deleted": permanent,
            "temporary_deleted": total - permanent,
        }
