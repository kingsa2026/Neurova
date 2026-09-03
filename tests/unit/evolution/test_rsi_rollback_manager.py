"""
RSI 回滚管理器测试

测试 RSI 的回滚管理功能
"""

import unittest
from unittest.mock import MagicMock, patch
from typing import Dict, List, Any

from neurova.evolution.rsi.rollback_manager import RSIRollbackManager


class TestRSIRollbackManager(unittest.TestCase):
    """测试 RSI 回滚管理器"""
    
    def setUp(self):
        """测试前准备"""
        self.manager = RSIRollbackManager()
    
    def test_initialization(self):
        """测试初始化"""
        # 验证默认参数
        self.assertEqual(self.manager.max_rollback_history, 100)
        self.assertEqual(len(self.manager.get_rollback_history()), 0)
    
    def test_create_snapshot(self):
        """测试创建快照"""
        # 创建系统状态
        system_state = {
            'sleep': {'base_decay_rate': 0.1},
            'emotion': {'decay_rate': 0.05},
        }
        
        # 创建快照
        snapshot_id = self.manager.create_snapshot(system_state)
        
        # 验证快照 ID
        self.assertIsNotNone(snapshot_id)
        self.assertIsInstance(snapshot_id, str)
        self.assertTrue(len(snapshot_id) > 0)
    
    def test_create_snapshot_unique_ids(self):
        """测试快照 ID 唯一性"""
        system_state = {'test': 'data'}
        
        # 创建两个快照
        snapshot_id1 = self.manager.create_snapshot(system_state)
        snapshot_id2 = self.manager.create_snapshot(system_state)
        
        # 验证 ID 不同
        self.assertNotEqual(snapshot_id1, snapshot_id2)
    
    def test_should_rollback_true(self):
        """测试应该回滚的情况"""
        # 模拟发散指标
        metrics = {
            'convergence_status': 'diverging',
            'roi': -0.1,
        }
        
        # 验证应该回滚
        self.assertTrue(self.manager.should_rollback(metrics))
    
    def test_should_rollback_false(self):
        """测试不应该回滚的情况"""
        # 模拟正常指标
        metrics = {
            'convergence_status': 'converging',
            'roi': 1.5,
        }
        
        # 验证不应该回滚
        self.assertFalse(self.manager.should_rollback(metrics))
    
    def test_execute_rollback(self):
        """测试执行回滚"""
        # 创建快照
        system_state = {'test': 'data'}
        snapshot_id = self.manager.create_snapshot(system_state)
        
        # 执行回滚
        result = self.manager.execute_rollback(snapshot_id)
        
        # 验证回滚成功
        self.assertTrue(result)
        
        # 验证回滚历史记录
        history = self.manager.get_rollback_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['snapshot_id'], snapshot_id)
    
    def test_execute_rollback_invalid_snapshot(self):
        """测试无效快照 ID 回滚"""
        # 执行回滚
        result = self.manager.execute_rollback('nonexistent_snapshot')
        
        # 验证回滚失败
        self.assertFalse(result)
    
    def test_get_rollback_history(self):
        """测试获取回滚历史"""
        # 创建多个快照并回滚
        system_state1 = {'test': 'data1'}
        system_state2 = {'test': 'data2'}
        
        snapshot_id1 = self.manager.create_snapshot(system_state1)
        snapshot_id2 = self.manager.create_snapshot(system_state2)
        
        self.manager.execute_rollback(snapshot_id1)
        self.manager.execute_rollback(snapshot_id2)
        
        # 获取历史
        history = self.manager.get_rollback_history()
        
        # 验证历史记录
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]['snapshot_id'], snapshot_id1)
        self.assertEqual(history[1]['snapshot_id'], snapshot_id2)


if __name__ == '__main__':
    unittest.main()