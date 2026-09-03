"""
RSI 部署控制器测试

测试 RSI 的部署控制功能
"""

import unittest
from unittest.mock import MagicMock, patch
from typing import Dict, List, Any

from neurova.evolution.rsi.deployment_controller import RSIDeploymentController


class TestRSIDeploymentController(unittest.TestCase):
    """测试 RSI 部署控制器"""
    
    def setUp(self):
        """测试前准备"""
        self.controller = RSIDeploymentController()
    
    def test_initialization(self):
        """测试初始化"""
        # 验证默认阶段为 Phase 0
        self.assertEqual(self.controller.get_current_phase(), 0)
    
    def test_can_auto_execute_phase_0(self):
        """测试 Phase 0 不能自动执行"""
        # Phase 0: 观察阶段，不能自动执行
        self.assertFalse(self.controller.can_auto_execute('low'))
        self.assertFalse(self.controller.can_auto_execute('medium'))
        self.assertFalse(self.controller.can_auto_execute('high'))
    
    def test_can_auto_execute_phase_1(self):
        """测试 Phase 1 不能自动执行"""
        # Phase 1: 手动阶段，不能自动执行
        self.controller.advance_phase()
        self.assertFalse(self.controller.can_auto_execute('low'))
        self.assertFalse(self.controller.can_auto_execute('medium'))
        self.assertFalse(self.controller.can_auto_execute('high'))
    
    def test_can_auto_execute_phase_2(self):
        """测试 Phase 2 可以自动执行低风险优化"""
        # Phase 2: 半自动阶段，可以自动执行低风险
        self.controller.advance_phase()
        self.controller.advance_phase()
        self.assertTrue(self.controller.can_auto_execute('low'))
        self.assertFalse(self.controller.can_auto_execute('medium'))
        self.assertFalse(self.controller.can_auto_execute('high'))
    
    def test_can_auto_execute_phase_3(self):
        """测试 Phase 3 可以自动执行中低风险优化"""
        # Phase 3: 有条件自动阶段，可以自动执行中低风险
        for _ in range(3):
            self.controller.advance_phase()
        self.assertTrue(self.controller.can_auto_execute('low'))
        self.assertTrue(self.controller.can_auto_execute('medium'))
        self.assertFalse(self.controller.can_auto_execute('high'))
    
    def test_can_auto_execute_phase_4(self):
        """测试 Phase 4 可以自动执行所有风险优化"""
        # Phase 4: 完全自动阶段，可以自动执行所有风险
        for _ in range(4):
            self.controller.advance_phase()
        self.assertTrue(self.controller.can_auto_execute('low'))
        self.assertTrue(self.controller.can_auto_execute('medium'))
        self.assertTrue(self.controller.can_auto_execute('high'))
    
    def test_evaluate_phase_transition(self):
        """测试评估阶段转换"""
        # 模拟正常指标
        metrics = {
            'convergence_status': 'converging',
            'roi': 1.5,
            'days_without_rollback': 10,
        }
        
        # 验证应该进入下一阶段
        self.assertTrue(self.controller.evaluate_phase_transition(metrics))
    
    def test_advance_phase(self):
        """测试进入下一阶段"""
        # 初始阶段为 0
        self.assertEqual(self.controller.get_current_phase(), 0)
        
        # 进入下一阶段
        new_phase = self.controller.advance_phase()
        self.assertEqual(new_phase, 1)
        self.assertEqual(self.controller.get_current_phase(), 1)
    
    def test_advance_phase_max(self):
        """测试不能超过 Phase 4"""
        # 进入到 Phase 4
        for _ in range(4):
            self.controller.advance_phase()
        
        # 验证已经在 Phase 4
        self.assertEqual(self.controller.get_current_phase(), 4)
        
        # 尝试进入下一阶段，应该还是 Phase 4
        new_phase = self.controller.advance_phase()
        self.assertEqual(new_phase, 4)
        self.assertEqual(self.controller.get_current_phase(), 4)


if __name__ == '__main__':
    unittest.main()