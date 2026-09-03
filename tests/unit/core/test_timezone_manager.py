"""
测试时区管理器模块
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from neurova.core.timezone_manager import (
    TimezoneInfo,
    TimezoneManager,
    get_timezone_manager,
    init_timezone_manager,
)


class TestTimezoneInfo:
    """测试TimezoneInfo类"""
    
    def test_create_timezone_info(self):
        """测试创建时区信息对象"""
        tz_info = TimezoneInfo(
            timezone_id="Asia/Shanghai",
            display_name="北京时间 (UTC+08:00)",
            offset="+08:00",
            is_dst=False,
        )
        
        assert tz_info.timezone_id == "Asia/Shanghai"
        assert tz_info.display_name == "北京时间 (UTC+08:00)"
        assert tz_info.offset == "+08:00"
        assert tz_info.is_dst is False
    
    def test_timezone_info_to_dict(self):
        """测试时区信息转换为字典"""
        tz_info = TimezoneInfo(
            timezone_id="America/New_York",
            display_name="纽约时间 (UTC-05:00)",
            offset="-05:00",
            is_dst=False,
        )
        
        tz_dict = tz_info.to_dict()
        
        assert tz_dict["timezone_id"] == "America/New_York"
        assert tz_dict["display_name"] == "纽约时间 (UTC-05:00)"
        assert tz_dict["offset"] == "-05:00"
        assert tz_dict["is_dst"] is False


class TestTimezoneManager:
    """测试TimezoneManager类"""
    
    def test_init_timezone_manager(self):
        """测试初始化时区管理器"""
        manager = TimezoneManager()
        
        assert manager is not None
        assert len(manager._all_timezones) > 0
    
    def test_get_all_timezones(self):
        """测试获取所有时区列表"""
        manager = TimezoneManager()
        timezones = manager.get_all_timezones()
        
        assert isinstance(timezones, list)
        assert len(timezones) > 0
        assert "Asia/Shanghai" in timezones
        assert "America/New_York" in timezones
    
    def test_get_common_timezones(self):
        """测试获取常用时区"""
        manager = TimezoneManager()
        common_tzs = manager.get_common_timezones()
        
        assert isinstance(common_tzs, dict)
        assert "Asia" in common_tzs
        assert "Europe" in common_tzs
        assert "America" in common_tzs
        assert "Asia/Shanghai" in common_tzs["Asia"]
    
    def test_get_timezone_info_valid(self):
        """测试获取有效的时区信息"""
        manager = TimezoneManager()
        tz_info = manager.get_timezone_info("Asia/Shanghai")
        
        assert tz_info is not None
        assert tz_info.timezone_id == "Asia/Shanghai"
        assert tz_info.offset.startswith("+")
    
    def test_get_timezone_info_invalid(self):
        """测试获取无效的时区信息"""
        manager = TimezoneManager()
        tz_info = manager.get_timezone_info("Invalid/Timezone")
        
        assert tz_info is None
    
    def test_get_all_timezone_info(self):
        """测试获取所有常用时区的详细信息"""
        manager = TimezoneManager()
        all_info = manager.get_all_timezone_info()
        
        assert isinstance(all_info, list)
        assert len(all_info) > 0
        for tz in all_info:
            assert "timezone_id" in tz
            assert "display_name" in tz
            assert "offset" in tz
    
    def test_is_valid_timezone_true(self):
        """测试有效的时区检查"""
        manager = TimezoneManager()
        
        assert manager.is_valid_timezone("Asia/Shanghai") is True
        assert manager.is_valid_timezone("America/New_York") is True
    
    def test_is_valid_timezone_false(self):
        """测试无效的时区检查"""
        manager = TimezoneManager()
        
        assert manager.is_valid_timezone("Invalid/Timezone") is False
        assert manager.is_valid_timezone("") is False
    
    @patch('neurova.core.timezone_manager.get_workspace_manager')
    def test_get_user_timezone(self, mock_get_workspace_manager):
        """测试获取用户时区"""
        # Mock workspace manager
        mock_workspace = MagicMock()
        mock_workspace.get_config.return_value = "America/Los_Angeles"
        mock_ws_manager = MagicMock()
        mock_ws_manager.get_workspace.return_value = mock_workspace
        mock_get_workspace_manager.return_value = mock_ws_manager
        
        manager = TimezoneManager()
        timezone_id = manager.get_user_timezone("test-user")
        
        assert timezone_id == "America/Los_Angeles"
        mock_workspace.get_config.assert_called_once_with("timezone", "Asia/Shanghai")
    
    @patch('neurova.core.timezone_manager.get_workspace_manager')
    def test_set_user_timezone_valid(self, mock_get_workspace_manager):
        """测试设置有效的用户时区"""
        # Mock workspace manager
        mock_workspace = MagicMock()
        mock_ws_manager = MagicMock()
        mock_ws_manager.get_workspace.return_value = mock_workspace
        mock_get_workspace_manager.return_value = mock_ws_manager
        
        manager = TimezoneManager()
        result = manager.set_user_timezone("test-user", "America/Los_Angeles")
        
        assert result is True
        mock_workspace.set_config.assert_called_once_with("timezone", "America/Los_Angeles")
    
    @patch('neurova.core.timezone_manager.get_workspace_manager')
    def test_set_user_timezone_invalid(self, mock_get_workspace_manager):
        """测试设置无效的用户时区"""
        manager = TimezoneManager()
        result = manager.set_user_timezone("test-user", "Invalid/Timezone")
        
        assert result is False
        mock_get_workspace_manager.assert_not_called()
    
    def test_convert_time(self):
        """测试时区转换"""
        manager = TimezoneManager()
        
        # 创建一个UTC时间
        utc_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        
        # 转换到上海时区
        shanghai_time = manager.convert_time(utc_time, "UTC", "Asia/Shanghai")
        
        assert shanghai_time is not None
        # 上海是UTC+8，所以12+8=20点
        assert shanghai_time.hour == 20
    
    def test_convert_time_invalid(self):
        """测试无效的时区转换"""
        manager = TimezoneManager()
        
        utc_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = manager.convert_time(utc_time, "Invalid/Timezone", "Asia/Shanghai")
        
        assert result is None
    
    @patch('neurova.core.timezone_manager.get_workspace_manager')
    def test_format_time_for_user(self, mock_get_workspace_manager):
        """测试根据用户时区格式化时间"""
        # Mock workspace manager
        mock_workspace = MagicMock()
        mock_workspace.get_config.return_value = "Asia/Shanghai"
        mock_ws_manager = MagicMock()
        mock_ws_manager.get_workspace.return_value = mock_workspace
        mock_get_workspace_manager.return_value = mock_ws_manager
        
        manager = TimezoneManager()
        utc_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        
        formatted = manager.format_time_for_user(utc_time, "test-user", "%Y-%m-%d %H:%M")
        
        assert "2024-01-01" in formatted
        # 上海时区的20点
        assert "20:00" in formatted
    
    @patch('neurova.core.timezone_manager.get_workspace_manager')
    def test_get_user_local_time(self, mock_get_workspace_manager):
        """测试获取用户本地时间"""
        # Mock workspace manager
        mock_workspace = MagicMock()
        mock_workspace.get_config.return_value = "Asia/Shanghai"
        mock_ws_manager = MagicMock()
        mock_ws_manager.get_workspace.return_value = mock_workspace
        mock_get_workspace_manager.return_value = mock_ws_manager
        
        manager = TimezoneManager()
        local_time = manager.get_user_local_time("test-user")
        
        assert isinstance(local_time, dict)
        assert "utc_time" in local_time
        assert "local_time" in local_time
        assert "timezone" in local_time
        assert local_time["timezone"] == "Asia/Shanghai"


class TestGlobalFunctions:
    """测试全局函数"""
    
    @patch('neurova.core.timezone_manager._timezone_manager', None)
    def test_get_timezone_manager(self):
        """测试获取全局时区管理器"""
        manager1 = get_timezone_manager()
        manager2 = get_timezone_manager()
        
        assert manager1 is manager2
    
    @patch('neurova.core.timezone_manager._timezone_manager', None)
    def test_init_timezone_manager(self):
        """测试初始化全局时区管理器"""
        manager1 = get_timezone_manager()
        manager2 = init_timezone_manager()
        
        assert manager1 is not manager2
