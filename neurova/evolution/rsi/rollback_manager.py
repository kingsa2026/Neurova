"""
RSI 回滚管理器

RSI 风险较高，必须具备自动回滚机制
"""

import logging
import uuid
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class RSIRollbackManager:
    """RSI 回滚管理器"""
    
    def __init__(self, max_rollback_history: int = 100):
        """
        初始化回滚管理器
        
        Args:
            max_rollback_history: 最大回滚历史记录数
        """
        self.max_rollback_history = max_rollback_history
        
        # 快照存储: {snapshot_id: system_state}
        self._snapshots: Dict[str, Dict[str, Any]] = {}
        
        # 回滚历史
        self._rollback_history: List[Dict[str, Any]] = []
        
        logger.info(f"RSIRollbackManager initialized with max_history={max_rollback_history}")
    
    def create_snapshot(self, system_state: Dict[str, Any]) -> str:
        """
        创建系统状态快照
        
        Args:
            system_state: 系统状态
            
        Returns:
            str: 快照 ID
        """
        # 生成唯一 ID
        snapshot_id = str(uuid.uuid4())
        
        # 存储快照
        self._snapshots[snapshot_id] = system_state.copy()
        
        logger.debug(f"Created snapshot: {snapshot_id}")
        return snapshot_id
    
    def should_rollback(self, metrics: Dict[str, Any]) -> bool:
        """
        判断是否应该回滚
        
        Args:
            metrics: 当前指标
            
        Returns:
            bool: 是否应该回滚
        """
        # 检查收敛状态
        convergence_status = metrics.get('convergence_status', '')
        if convergence_status == 'diverging':
            logger.warning("Divergence detected, should rollback")
            return True
        
        # 检查 ROI
        roi = metrics.get('roi', 0)
        if roi < 0:
            logger.warning(f"Negative ROI detected: {roi}, should rollback")
            return True
        
        return False
    
    def execute_rollback(self, snapshot_id: str) -> bool:
        """
        执行回滚到指定快照
        
        Args:
            snapshot_id: 快照 ID
            
        Returns:
            bool: 是否成功回滚
        """
        # 检查快照是否存在
        if snapshot_id not in self._snapshots:
            logger.error(f"Snapshot not found: {snapshot_id}")
            return False
        
        # 获取快照
        system_state = self._snapshots[snapshot_id]
        
        # 记录回滚历史
        rollback_record = {
            'snapshot_id': snapshot_id,
            'timestamp': datetime.now().isoformat(),
            'system_state': system_state,
        }
        self._rollback_history.append(rollback_record)
        
        # 清理旧历史记录
        if len(self._rollback_history) > self.max_rollback_history:
            self._rollback_history = self._rollback_history[-self.max_rollback_history:]
        
        logger.info(f"Executed rollback to snapshot: {snapshot_id}")
        return True
    
    def get_rollback_history(self) -> List[Dict[str, Any]]:
        """
        获取回滚历史
        
        Returns:
            List[Dict[str, Any]]: 回滚历史记录
        """
        return self._rollback_history.copy()


def create_rollback_manager(max_rollback_history: int = 100) -> RSIRollbackManager:
    """
    创建 RSI 回滚管理器实例
    
    Args:
        max_rollback_history: 最大回滚历史记录数
        
    Returns:
        RSIRollbackManager: RSI 回滚管理器实例
    """
    return RSIRollbackManager(max_rollback_history)