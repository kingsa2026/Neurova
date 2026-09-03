"""
测试日志级别模块
"""
import pytest
from neurova.core.log_level import LogLevel


class TestLogLevel:
    """测试LogLevel枚举类"""
    
    def test_log_level_members(self):
        """测试枚举成员是否正确定义"""
        assert LogLevel.DEBUG.value == 10
        assert LogLevel.INFO.value == 20
        assert LogLevel.WARNING.value == 30
        assert LogLevel.ERROR.value == 40
        assert LogLevel.CRITICAL.value == 50
    
    def test_log_level_order(self):
        """测试日志级别的顺序关系"""
        assert LogLevel.DEBUG < LogLevel.INFO
        assert LogLevel.INFO < LogLevel.WARNING
        assert LogLevel.WARNING < LogLevel.ERROR
        assert LogLevel.ERROR < LogLevel.CRITICAL
    
    def test_log_level_comparison(self):
        """测试日志级别的比较操作"""
        assert LogLevel.DEBUG <= LogLevel.INFO
        assert LogLevel.CRITICAL >= LogLevel.ERROR
        assert LogLevel.WARNING == LogLevel.WARNING
        assert LogLevel.INFO != LogLevel.DEBUG
    
    def test_log_level_from_value(self):
        """测试从数值创建LogLevel"""
        assert LogLevel(10) == LogLevel.DEBUG
        assert LogLevel(20) == LogLevel.INFO
        assert LogLevel(30) == LogLevel.WARNING
        assert LogLevel(40) == LogLevel.ERROR
        assert LogLevel(50) == LogLevel.CRITICAL
    
    def test_log_level_from_name(self):
        """测试从名称创建LogLevel"""
        assert LogLevel['DEBUG'] == LogLevel.DEBUG
        assert LogLevel['INFO'] == LogLevel.INFO
        assert LogLevel['WARNING'] == LogLevel.WARNING
        assert LogLevel['ERROR'] == LogLevel.ERROR
        assert LogLevel['CRITICAL'] == LogLevel.CRITICAL
    
    def test_log_level_iteration(self):
        """测试枚举的迭代功能"""
        levels = list(LogLevel)
        assert len(levels) == 5
        assert LogLevel.DEBUG in levels
        assert LogLevel.INFO in levels
        assert LogLevel.WARNING in levels
        assert LogLevel.ERROR in levels
        assert LogLevel.CRITICAL in levels
    
    def test_log_level_str_representation(self):
        """测试日志级别的字符串表示"""
        assert str(LogLevel.DEBUG) == "LogLevel.DEBUG"
        assert str(LogLevel.INFO) == "LogLevel.INFO"
    
    def test_log_level_int_operations(self):
        """测试作为IntEnum的数值操作"""
        assert int(LogLevel.DEBUG) == 10
        assert LogLevel.INFO + 10 == 30
        assert LogLevel.CRITICAL - 10 == 40
    
    def test_invalid_log_level_value(self):
        """测试无效的日志级别值"""
        with pytest.raises(ValueError):
            LogLevel(99)
    
    def test_invalid_log_level_name(self):
        """测试无效的日志级别名称"""
        with pytest.raises(KeyError):
            LogLevel['INVALID']
