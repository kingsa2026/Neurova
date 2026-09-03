"""
收敛性分析器测试

测试 RSI 的收敛性数学分析功能
"""

import unittest
from unittest.mock import MagicMock, patch
from typing import Dict, List, Any


class TestConvergenceAnalyzer(unittest.TestCase):
    """测试收敛性分析器"""
    
    def setUp(self):
        """测试前准备"""
        from neurova.evolution.rsi.convergence_analyzer import ConvergenceAnalyzer
        
        self.analyzer = ConvergenceAnalyzer(
            window_size=10,
            convergence_threshold=0.01,
            divergence_threshold=-0.05
        )
    
    def test_initialization(self):
        """测试初始化"""
        self.assertEqual(self.analyzer.window_size, 10)
        self.assertEqual(self.analyzer.convergence_threshold, 0.01)
        self.assertEqual(self.analyzer.divergence_threshold, -0.05)
        self.assertEqual(len(self.analyzer.gain_history), 0)
        self.assertEqual(len(self.analyzer.cost_history), 0)
    
    def test_record_iteration(self):
        """测试记录迭代"""
        # 记录一些迭代
        self.analyzer.record_iteration(gain=0.1, cost=0.05)
        self.analyzer.record_iteration(gain=0.08, cost=0.06)
        self.analyzer.record_iteration(gain=0.05, cost=0.07)
        
        # 验证记录
        self.assertEqual(len(self.analyzer.gain_history), 3)
        self.assertEqual(len(self.analyzer.cost_history), 3)
        self.assertEqual(self.analyzer.gain_history[-1], 0.05)
        self.assertEqual(self.analyzer.cost_history[-1], 0.07)
    
    def test_record_iteration_window_limit(self):
        """测试窗口大小限制"""
        # 记录超过窗口大小的数据
        for i in range(25):
            self.analyzer.record_iteration(gain=0.1 - i * 0.01, cost=0.05)
        
        # 验证窗口限制
        self.assertEqual(len(self.analyzer.gain_history), 20)  # window_size * 2
        self.assertEqual(len(self.analyzer.cost_history), 20)
    
    def test_analyze_convergence_insufficient_data(self):
        """测试数据不足时的收敛分析"""
        # 只记录少量数据
        self.analyzer.record_iteration(gain=0.1, cost=0.05)
        self.analyzer.record_iteration(gain=0.08, cost=0.06)
        
        result = self.analyzer.analyze_convergence()
        
        # 验证返回 insufficient_data
        self.assertEqual(result['status'], 'insufficient_data')
        self.assertEqual(result['confidence'], 0.0)
        self.assertIn('需要更多数据', result['recommendation'])
    
    def test_analyze_convergence_converging(self):
        """测试收敛趋势检测"""
        # 模拟收敛趋势（增益逐渐减小）
        gains = [0.1, 0.08, 0.06, 0.04, 0.03, 0.02, 0.015, 0.012, 0.011, 0.0105]
        costs = [0.05] * 10
        
        for gain, cost in zip(gains, costs):
            self.analyzer.record_iteration(gain=gain, cost=cost)
        
        result = self.analyzer.analyze_convergence()
        
        # 验证收敛状态
        self.assertIn(result['status'], ['converging', 'converged'])
        self.assertGreater(result['confidence'], 0.5)
    
    def test_analyze_convergence_converged(self):
        """测试已收敛状态"""
        # 模拟已收敛（增益非常小）
        gains = [0.001, 0.0008, 0.0006, 0.0005, 0.0004, 0.0003, 0.0002, 0.0001, 0.00005, 0.00001]
        costs = [0.05] * 10
        
        for gain, cost in zip(gains, costs):
            self.analyzer.record_iteration(gain=gain, cost=cost)
        
        result = self.analyzer.analyze_convergence()
        
        # 验证收敛状态
        self.assertEqual(result['status'], 'converged')
        self.assertGreater(result['confidence'], 0.8)
    
    def test_analyze_convergence_diverging(self):
        """测试发散状态"""
        # 模拟发散（负增益）
        gains = [-0.01, -0.02, -0.03, -0.04, -0.05, -0.06, -0.07, -0.08, -0.09, -0.10]
        costs = [0.05] * 10
        
        for gain, cost in zip(gains, costs):
            self.analyzer.record_iteration(gain=gain, cost=cost)
        
        result = self.analyzer.analyze_convergence()
        
        # 验证发散状态
        self.assertEqual(result['status'], 'diverging')
        self.assertGreater(result['confidence'], 0.7)
    
    def test_compute_roi(self):
        """测试 ROI 计算"""
        # 记录一些迭代
        self.analyzer.record_iteration(gain=0.1, cost=0.05)
        self.analyzer.record_iteration(gain=0.08, cost=0.06)
        self.analyzer.record_iteration(gain=0.05, cost=0.07)
        
        roi = self.analyzer.compute_roi()
        
        # 验证 ROI 计算
        expected_roi = (0.1 + 0.08 + 0.05) / (0.05 + 0.06 + 0.07)
        self.assertAlmostEqual(roi, expected_roi, places=2)
    
    def test_compute_roi_zero_cost(self):
        """测试零成本时的 ROI 计算"""
        # 记录零成本迭代
        self.analyzer.record_iteration(gain=0.1, cost=0.0)
        self.analyzer.record_iteration(gain=0.08, cost=0.0)
        
        roi = self.analyzer.compute_roi()
        
        # 验证除零保护
        self.assertEqual(roi, 0.0)
    
    def test_predict_convergence_point(self):
        """测试收敛点预测"""
        # 模拟收敛趋势
        gains = [0.1, 0.08, 0.06, 0.04, 0.03, 0.02, 0.015, 0.012, 0.011, 0.0105]
        costs = [0.05] * 10
        
        for gain, cost in zip(gains, costs):
            self.analyzer.record_iteration(gain=gain, cost=cost)
        
        prediction = self.analyzer.predict_convergence_point()
        
        # 验证预测结果
        if prediction is not None:
            self.assertIsInstance(prediction, int)
            self.assertGreater(prediction, 0)
    
    def test_predict_convergence_point_insufficient_data(self):
        """测试数据不足时的收敛点预测"""
        # 只记录少量数据
        self.analyzer.record_iteration(gain=0.1, cost=0.05)
        
        prediction = self.analyzer.predict_convergence_point()
        
        # 验证无法预测
        self.assertIsNone(prediction)
    
    def test_is_worth_continuing_true(self):
        """测试值得继续进化"""
        # 模拟正 ROI
        self.analyzer.record_iteration(gain=0.1, cost=0.05)
        self.analyzer.record_iteration(gain=0.08, cost=0.06)
        self.analyzer.record_iteration(gain=0.05, cost=0.07)
        
        result = self.analyzer.is_worth_continuing()
        
        # 验证值得继续
        self.assertTrue(result)
    
    def test_is_worth_continuing_false_diverging(self):
        """测试发散时不值得继续"""
        # 模拟发散
        gains = [-0.01, -0.02, -0.03, -0.04, -0.05, -0.06, -0.07, -0.08, -0.09, -0.10]
        costs = [0.05] * 10
        
        for gain, cost in zip(gains, costs):
            self.analyzer.record_iteration(gain=gain, cost=cost)
        
        result = self.analyzer.is_worth_continuing()
        
        # 验证不值得继续
        self.assertFalse(result)
    
    def test_is_worth_continuing_false_negative_roi(self):
        """测试负 ROI 时不值得继续"""
        # 模拟负 ROI
        self.analyzer.record_iteration(gain=0.01, cost=0.1)
        self.analyzer.record_iteration(gain=0.01, cost=0.1)
        self.analyzer.record_iteration(gain=0.01, cost=0.1)
        
        result = self.analyzer.is_worth_continuing()
        
        # 验证不值得继续
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()