"""
测试时区管理器模块（对齐 neurova/core/timezone_manager.py 真实契约）
"""

import pytest
from datetime import datetime, timezone

from neurova.core.timezone_manager import (
    TimezoneInfo,
    TimezoneManager,
    get_timezone_manager,
    init_timezone_manager,
    reset_timezone_manager,
)


class TestTimezoneInfo:
    """测试TimezoneInfo类"""

    def test_create_timezone_info(self):
        """测试创建时区信息对象（字段面 name/offset/utc_offset/description）"""
        tz_info = TimezoneInfo(
            name="Asia/Shanghai",
            offset="+0800",
            utc_offset=8.0,
            description="中国标准时间",
        )

        assert tz_info.name == "Asia/Shanghai"
        assert tz_info.offset == "+0800"
        assert tz_info.utc_offset == 8.0
        assert tz_info.description == "中国标准时间"

    def test_timezone_info_to_dict(self):
        """测试时区信息转换为字典"""
        tz_info = TimezoneInfo(
            name="America/New_York",
            offset="-0500",
            utc_offset=-5.0,
        )

        tz_dict = tz_info.to_dict()

        assert tz_dict["name"] == "America/New_York"
        assert tz_dict["offset"] == "-0500"
        assert tz_dict["utc_offset"] == -5.0
        assert "description" in tz_dict


class TestTimezoneManager:
    """测试TimezoneManager类"""

    def test_init_timezone_manager(self):
        """测试初始化时区管理器（时区数据已装载）"""
        manager = TimezoneManager()

        assert manager is not None
        assert len(manager._timezones) > 0

    def test_get_all_timezones(self):
        """测试获取所有时区列表"""
        manager = TimezoneManager()
        timezones = manager.get_all_timezones()

        assert isinstance(timezones, list)
        assert len(timezones) > 0
        assert "Asia/Shanghai" in timezones
        assert "America/New_York" in timezones
        # 已排序
        assert timezones == sorted(timezones)

    def test_get_common_timezones(self):
        """测试获取常用时区（契约：返回字符串列表）"""
        manager = TimezoneManager()
        common_tzs = manager.get_common_timezones()

        assert isinstance(common_tzs, list)
        assert "Asia/Shanghai" in common_tzs
        assert "Europe/London" in common_tzs
        assert "America/New_York" in common_tzs

    def test_get_timezone_info_valid(self):
        """测试获取有效的时区信息"""
        manager = TimezoneManager()
        tz_info = manager.get_timezone_info("Asia/Shanghai")

        assert tz_info is not None
        assert tz_info.name == "Asia/Shanghai"
        assert tz_info.utc_offset == 8.0

    def test_get_timezone_info_invalid(self):
        """测试获取无效的时区信息"""
        manager = TimezoneManager()

        assert manager.get_timezone_info("Invalid/Timezone") is None

    def test_get_all_timezone_info(self):
        """测试获取所有时区的详细信息（TimezoneInfo 对象列表）"""
        manager = TimezoneManager()
        all_info = manager.get_all_timezone_info()

        assert isinstance(all_info, list)
        assert len(all_info) > 0
        for tz in all_info:
            assert isinstance(tz, TimezoneInfo)
            assert tz.name
            assert isinstance(tz.utc_offset, float)

    def test_is_valid_timezone(self):
        """测试时区有效性检查"""
        manager = TimezoneManager()

        assert manager.is_valid_timezone("Asia/Shanghai") is True
        assert manager.is_valid_timezone("America/New_York") is True
        assert manager.is_valid_timezone("Invalid/Timezone") is False
        assert manager.is_valid_timezone("") is False

    def test_get_user_timezone_default(self):
        """测试获取用户时区（默认 Asia/Shanghai）"""
        manager = TimezoneManager()

        assert manager.get_user_timezone("test-user") == "Asia/Shanghai"

    def test_set_user_timezone_valid(self):
        """测试设置有效的用户时区（参数序：timezone_name, user_id）"""
        manager = TimezoneManager()

        result = manager.set_user_timezone("America/Los_Angeles", "test-user")

        assert result is True
        assert manager.get_user_timezone("test-user") == "America/Los_Angeles"

    def test_set_user_timezone_invalid(self):
        """测试设置无效的用户时区"""
        manager = TimezoneManager()

        assert manager.set_user_timezone("Invalid/Timezone", "test-user") is False
        # 未写入
        assert manager.get_user_timezone("test-user") == "Asia/Shanghai"

    def test_convert_time(self):
        """测试时区转换"""
        manager = TimezoneManager()

        utc_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        shanghai_time = manager.convert_time(utc_time, "UTC", "Asia/Shanghai")

        assert shanghai_time is not None
        assert shanghai_time.hour == 20  # UTC+8

    def test_convert_time_invalid_returns_original(self):
        """无效目标时区返回原时间（不抛错）"""
        manager = TimezoneManager()

        utc_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = manager.convert_time(utc_time, "UTC", "Invalid/Timezone")

        assert result is not None
        assert result.hour == 12

    def test_format_time_for_user(self):
        """测试根据用户时区格式化时间"""
        manager = TimezoneManager()
        manager.set_user_timezone("Asia/Shanghai", "test-user")

        utc_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        formatted = manager.format_time_for_user(utc_time, "test-user", "%Y-%m-%d %H:%M")

        assert "2024-01-01" in formatted
        assert "20:00" in formatted

    def test_get_user_local_time(self):
        """测试获取用户本地时间（返回 datetime）"""
        manager = TimezoneManager()
        manager.set_user_timezone("Asia/Shanghai", "test-user")

        utc_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        local_time = manager.get_user_local_time("test-user", utc_time)

        assert isinstance(local_time, datetime)
        assert local_time.hour == 20

    def test_get_timezone_offset(self):
        """测试获取时区偏移量"""
        manager = TimezoneManager()

        assert manager.get_timezone_offset("Asia/Shanghai") == 8.0
        assert manager.get_timezone_offset("Invalid/Timezone") is None

    def test_search_timezones(self):
        """测试时区搜索"""
        manager = TimezoneManager()

        results = manager.search_timezones("Shanghai")
        assert any(tz.name == "Asia/Shanghai" for tz in results)

        assert manager.search_timezones("%%no-such-zone%%") == []


class TestGlobalFunctions:
    """测试全局函数"""

    def test_get_timezone_manager(self):
        """测试获取全局时区管理器"""
        reset_timezone_manager()
        manager1 = get_timezone_manager()
        manager2 = get_timezone_manager()

        assert manager1 is manager2

    def test_init_timezone_manager(self):
        """测试初始化全局时区管理器（重建实例）"""
        reset_timezone_manager()
        manager1 = get_timezone_manager()
        manager2 = init_timezone_manager()

        assert manager1 is not manager2

    def test_reset_timezone_manager(self):
        """测试重置全局时区管理器"""
        reset_timezone_manager()
        manager1 = get_timezone_manager()
        reset_timezone_manager()
        manager2 = get_timezone_manager()

        assert manager1 is not manager2
