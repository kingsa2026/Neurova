"""
RSI 仪表盘测试

测试 RSI 的仪表盘功能
"""

import unittest
from unittest.mock import MagicMock, patch
from typing import Dict, List, Any

from neurova.evolution.rsi.dashboard import RSIDashboard
from neurova.evolution.rsi.metrics import RSIMetrics
from neurova.evolution.rsi.convergence_analyzer import ConvergenceAnalyzer


class TestRSIDashboard(unittest.TestCase):
    """测试 RSI 仪表盘"""
    
    def setUp(self):
        """测试前准备"""
        self.metrics = RSIMetrics()
        self.convergence_analyzer = ConvergenceAnalyzer()
        self.dashboard = RSIDashboard(self.metrics, self.convergence_analyzer)
    
    def test_initialization(self):
        """测试初始化"""
        # 验证依赖注入
        self.assertEqual(self.dashboard.metrics, self.metrics)
        self.assertEqual(self.dashboard.convergence_analyzer, self.convergence_analyzer)
    
    def test_get_overview(self):
        """测试获取概览数据"""
        # 记录一些指标
        self.metrics.record_metric(RSIMetrics.RSI_CYCLES_TOTAL, 10)
        self.metrics.record_metric(RSIMetrics.RSI_IMPROVEMENT_RATE, 0.15)
        self.metrics.record_metric(RSIMetrics.RSI_CONVERGENCE_ROI, 1.5)
        
        # 获取概览数据
        overview = self.dashboard.get_overview()
        
        # 验证概览数据
        self.assertIn('metrics', overview)
        self.assertIn('alerts', overview)
        self.assertIn('summary', overview)
        self.assertIn('convergence', overview)
    
    def test_get_convergence_chart(self):
        """测试获取收敛性趋势图数据"""
        # 记录一些迭代
        self.convergence_analyzer.record_iteration(0.1, 0.05)
        self.convergence_analyzer.record_iteration(0.08, 0.04)
        self.convergence_analyzer.record_iteration(0.06, 0.03)
        
        # 获取趋势图数据
        chart_data = self.dashboard.get_convergence_chart()
        
        # 验证趋势图数据
        self.assertIn('iterations', chart_data)
        self.assertIn('gains', chart_data)
        self.assertIn('costs', chart_data)
        self.assertIn('roi_trend', chart_data)
    
    def test_get_gate_pass_rate(self):
        """测试获取棘轮门通过率"""
        # 记录一些指标
        self.metrics.record_metric(RSIMetrics.RSI_CANDIDATES_GENERATED, 10)
        self.metrics.record_metric(RSIMetrics.RSI_CANDIDATES_PRUNED, 3)
        
        # 获取通过率数据
        pass_rate_data = self.dashboard.get_gate_pass_rate()
        
        # 验证通过率数据
        self.assertIn('total_candidates', pass_rate_data)
        self.assertIn('pruned_candidates', pass_rate_data)
        self.assertIn('pass_rate', pass_rate_data)
    
    def test_get_candidate_statistics(self):
        """测试获取候选方案统计"""
        # 记录一些指标
        self.metrics.record_metric(RSIMetrics.RSI_CANDIDATES_GENERATED, 15)
        self.metrics.record_metric(RSIMetrics.RSI_CANDIDATES_PRUNED, 5)
        self.metrics.record_metric(RSIMetrics.RSI_GATE_FAILURES, 2)
        
        # 获取统计数据
        stats = self.dashboard.get_candidate_statistics()
        
        # 验证统计数据
        self.assertIn('total_generated', stats)
        self.assertIn('total_pruned', stats)
        self.assertIn('gate_failures', stats)
        self.assertIn('success_rate', stats)
    
    def test_get_rollback_history(self):
        """测试获取回滚历史"""
        # 获取回滚历史
        history = self.dashboard.get_rollback_history()
        
        # 验证返回列表
        self.assertIsInstance(history, list)


if __name__ == '__main__':
    unittest.main()