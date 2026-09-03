"""
RSI 监控指标测试

测试 RSI 的监控指标功能
"""

import unittest
from unittest.mock import MagicMock, patch
from typing import Dict, List, Any

from neurova.evolution.rsi.metrics import RSIMetrics, Alert, AlertLevel


class TestRSIMetrics(unittest.TestCase):
    """测试 RSI 监控指标管理器"""
    
    def setUp(self):
        """测试前准备"""
        from neurova.evolution.rsi.metrics import RSIMetrics
        
        self.metrics = RSIMetrics()
    
    def test_initialization(self):
        """测试初始化"""
        # 验证所有指标初始化为 0
        self.assertEqual(self.metrics.get_metric(RSIMetrics.RSI_CYCLES_TOTAL), 0)
        self.assertEqual(self.metrics.get_metric(RSIMetrics.RSI_IMPROVEMENT_RATE), 0)
        self.assertEqual(self.metrics.get_metric(RSIMetrics.RSI_CONVERGENCE_ROI), 0)
        self.assertEqual(self.metrics.get_metric(RSIMetrics.RSI_ROLLBACK_COUNT), 0)
        self.assertEqual(self.metrics.get_metric(RSIMetrics.RSI_CANDIDATES_GENERATED), 0)
        self.assertEqual(self.metrics.get_metric(RSIMetrics.RSI_CANDIDATES_PRUNED), 0)
        self.assertEqual(self.metrics.get_metric(RSIMetrics.RSI_GATE_FAILURES), 0)
    
    def test_record_metric(self):
        """测试记录指标"""
        # 记录指标
        self.metrics.record_metric(RSIMetrics.RSI_CYCLES_TOTAL, 10)
        self.metrics.record_metric(RSIMetrics.RSI_IMPROVEMENT_RATE, 0.15)
        
        # 验证记录
        self.assertEqual(self.metrics.get_metric(RSIMetrics.RSI_CYCLES_TOTAL), 10)
        self.assertEqual(self.metrics.get_metric(RSIMetrics.RSI_IMPROVEMENT_RATE), 0.15)
    
    def test_record_metric_update(self):
        """测试更新指标"""
        # 记录指标
        self.metrics.record_metric(RSIMetrics.RSI_CYCLES_TOTAL, 10)
        
        # 更新指标
        self.metrics.record_metric(RSIMetrics.RSI_CYCLES_TOTAL, 20)
        
        # 验证更新
        self.assertEqual(self.metrics.get_metric(RSIMetrics.RSI_CYCLES_TOTAL), 20)
    
    def test_get_metric_nonexistent(self):
        """测试获取不存在的指标"""
        result = self.metrics.get_metric("nonexistent_metric")
        self.assertIsNone(result)
    
    def test_check_alerts_info(self):
        """测试 INFO 级别告警"""
        # 模拟 RSI 循环完成
        self.metrics.record_metric(RSIMetrics.RSI_CYCLES_TOTAL, 1)
        
        alerts = self.metrics.check_alerts()
        
        # 验证 INFO 告警
        info_alerts = [a for a in alerts if a.level == AlertLevel.INFO]
        self.assertGreater(len(info_alerts), 0)
    
    def test_check_alerts_warning(self):
        """测试 WARNING 级别告警"""
        # 模拟低 ROI
        self.metrics.record_metric(RSIMetrics.RSI_CONVERGENCE_ROI, 0.05)
        
        alerts = self.metrics.check_alerts()
        
        # 验证 WARNING 告警
        warning_alerts = [a for a in alerts if a.level == AlertLevel.WARNING]
        self.assertGreater(len(warning_alerts), 0)
    
    def test_check_alerts_error(self):
        """测试 ERROR 级别告警"""
        # 模拟连续失败
        self.metrics.record_metric(RSIMetrics.RSI_GATE_FAILURES, 3)
        
        alerts = self.metrics.check_alerts()
        
        # 验证 ERROR 告警
        error_alerts = [a for a in alerts if a.level == AlertLevel.ERROR]
        self.assertGreater(len(error_alerts), 0)
    
    def test_check_alerts_critical(self):
        """测试 CRITICAL 级别告警"""
        # 模拟发散检测（负 ROI）
        self.metrics.record_metric(RSIMetrics.RSI_CONVERGENCE_ROI, -0.1)
        
        alerts = self.metrics.check_alerts()
        
        # 验证 CRITICAL 告警
        critical_alerts = [a for a in alerts if a.level == AlertLevel.CRITICAL]
        self.assertGreater(len(critical_alerts), 0)
    
    def test_get_dashboard_data(self):
        """测试获取仪表盘数据"""
        # 记录一些指标
        self.metrics.record_metric(RSIMetrics.RSI_CYCLES_TOTAL, 10)
        self.metrics.record_metric(RSIMetrics.RSI_IMPROVEMENT_RATE, 0.15)
        self.metrics.record_metric(RSIMetrics.RSI_CONVERGENCE_ROI, 1.5)
        
        dashboard_data = self.metrics.get_dashboard_data()
        
        # 验证仪表盘数据
        self.assertIn('metrics', dashboard_data)
        self.assertIn('alerts', dashboard_data)
        self.assertIn('summary', dashboard_data)
        
        # 验证指标数据
        self.assertEqual(dashboard_data['metrics'][RSIMetrics.RSI_CYCLES_TOTAL], 10)
        self.assertEqual(dashboard_data['metrics'][RSIMetrics.RSI_IMPROVEMENT_RATE], 0.15)
        self.assertEqual(dashboard_data['metrics'][RSIMetrics.RSI_CONVERGENCE_ROI], 1.5)


if __name__ == '__main__':
    unittest.main()