"""
Neurova 时区管理器

功能:
1. 提供完整的时区列表（支持全球主要时区）
2. 时区信息查询（名称、偏移量、UTC偏移等）
3. 用户时区偏好管理
4. 时间转换工具
5. 与用户工作空间集成
"""

import datetime
import threading
import zoneinfo
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class TimezoneInfo:
    """
    时区信息数据类
    """

    def __init__(self, name: str, offset: str, utc_offset: float, description: str = ""):
        """
        初始化时区信息

        Args:
            name: 时区名称，如 "Asia/Shanghai"
            offset: 偏移量字符串，如 "+08:00"
            utc_offset: UTC偏移小时数，如 8.0
            description: 描述
        """
        self.name = name
        self.offset = offset
        self.utc_offset = utc_offset
        self.description = description

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "offset": self.offset,
            "utc_offset": self.utc_offset,
            "description": self.description,
        }


class TimezoneManager:
    """
    时区管理器

    管理时区信息、用户时区偏好和时间转换。
    """

    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化时区管理器

        Args:
            config: 配置字典
        """
        self._config = config or {}
        self._lock = threading.RLock()

        # 时区缓存
        self._timezones: Dict[str, TimezoneInfo] = {}
        self._common_timezones: List[str] = []

        # 用户时区偏好
        self._user_timezones: Dict[str, str] = {}

        # 加载时区数据
        self._load_timezones()

        logger.info("TimezoneManager 初始化完成")

    def _load_timezones(self) -> None:
        """加载时区数据"""
        try:
            # 获取所有可用时区
            all_zones = zoneinfo.available_timezones()

            # 构建时区信息
            for zone_name in all_zones:
                try:
                    zone_info = ZoneInfo(zone_name)
                    now = datetime.datetime.now(zone_info)
                    offset = now.strftime("%z")
                    utc_offset = now.utcoffset().total_seconds() / 3600

                    # 生成描述
                    description = self._generate_description(zone_name)

                    self._timezones[zone_name] = TimezoneInfo(
                        name=zone_name, offset=offset, utc_offset=utc_offset, description=description
                    )
                except Exception as e:
                    logger.debug("加载时区失败 %s: %s", zone_name, e)

            # 加载常用时区
            self._common_timezones = self._get_common_timezone_list()

            logger.debug("加载了 %s 个时区", len(self._timezones))

        except Exception as e:
            logger.error("加载时区数据失败: %s", e)

    def _generate_description(self, zone_name: str) -> str:
        """
        生成时区描述

        Args:
            zone_name: 时区名称

        Returns:
            描述字符串
        """
        # 常用时区描述
        descriptions = {
            "Asia/Shanghai": "中国标准时间",
            "Asia/Tokyo": "日本标准时间",
            "America/New_York": "美国东部时间",
            "America/Los_Angeles": "美国太平洋时间",
            "Europe/London": "格林威治标准时间",
            "Europe/Paris": "中欧时间",
            "Australia/Sydney": "澳大利亚东部时间",
            "UTC": "协调世界时",
        }

        return descriptions.get(zone_name, zone_name.replace("_", " ").replace("/", " / "))

    def _get_common_timezone_list(self) -> List[str]:
        """
        获取常用时区列表

        Returns:
            常用时区名称列表
        """
        return [
            "UTC",
            "Asia/Shanghai",
            "Asia/Tokyo",
            "Asia/Seoul",
            "Asia/Singapore",
            "Asia/Kolkata",
            "Asia/Dubai",
            "Europe/London",
            "Europe/Paris",
            "Europe/Berlin",
            "Europe/Moscow",
            "America/New_York",
            "America/Chicago",
            "America/Denver",
            "America/Los_Angeles",
            "America/Sao_Paulo",
            "Australia/Sydney",
            "Australia/Melbourne",
            "Pacific/Auckland",
        ]

    def get_all_timezones(self) -> List[str]:
        """
        获取所有时区名称

        Returns:
            时区名称列表
        """
        with self._lock:
            return sorted(list(self._timezones.keys()))

    def get_common_timezones(self) -> List[str]:
        """
        获取常用时区列表

        Returns:
            常用时区名称列表
        """
        with self._lock:
            return self._common_timezones.copy()

    def get_timezone_info(self, timezone_name: str) -> Optional[TimezoneInfo]:
        """
        获取时区信息

        Args:
            timezone_name: 时区名称

        Returns:
            时区信息，不存在返回 None
        """
        with self._lock:
            return self._timezones.get(timezone_name)

    def get_all_timezone_info(self) -> List[TimezoneInfo]:
        """
        获取所有时区信息

        Returns:
            时区信息列表
        """
        with self._lock:
            return list(self._timezones.values())

    def is_valid_timezone(self, timezone_name: str) -> bool:
        """
        检查时区是否有效

        Args:
            timezone_name: 时区名称

        Returns:
            是否有效
        """
        with self._lock:
            return timezone_name in self._timezones

    def get_user_timezone(self, user_id: str = "default") -> str:
        """
        获取用户时区

        Args:
            user_id: 用户ID

        Returns:
            时区名称
        """
        with self._lock:
            return self._user_timezones.get(user_id, "Asia/Shanghai")

    def set_user_timezone(self, timezone_name: str, user_id: str = "default") -> bool:
        """
        设置用户时区

        Args:
            timezone_name: 时区名称
            user_id: 用户ID

        Returns:
            是否设置成功
        """
        with self._lock:
            if not self.is_valid_timezone(timezone_name):
                logger.warning("无效的时区: %s", timezone_name)
                return False

            self._user_timezones[user_id] = timezone_name
            logger.info("用户 %s 时区设置为: %s", user_id, timezone_name)
            return True

    def get_user_local_time(self, user_id: str = "default", utc_time: datetime.datetime = None) -> datetime.datetime:
        """
        获取用户本地时间

        Args:
            user_id: 用户ID
            utc_time: UTC时间，默认为当前时间

        Returns:
            用户本地时间
        """
        with self._lock:
            timezone_name = self.get_user_timezone(user_id)

            if utc_time is None:
                utc_time = datetime.datetime.now(datetime.timezone.utc)

            # 转换时区
            try:
                zone_info = ZoneInfo(timezone_name)
                return utc_time.astimezone(zone_info)
            except Exception as e:
                logger.error("时间转换失败: %s", e)
                return utc_time

    def convert_time(self, time_value: datetime.datetime, from_timezone: str, to_timezone: str) -> datetime.datetime:
        """
        转换时间

        Args:
            time_value: 时间值
            from_timezone: 源时区
            to_timezone: 目标时区

        Returns:
            转换后的时间
        """
        with self._lock:
            try:
                # 确保时间有时区信息
                if time_value.tzinfo is None:
                    # 假设是UTC时间
                    time_value = time_value.replace(tzinfo=datetime.timezone.utc)

                # 转换到目标时区
                to_zone = ZoneInfo(to_timezone)
                return time_value.astimezone(to_zone)

            except Exception as e:
                logger.error("时间转换失败: %s", e)
                return time_value

    def format_time_for_user(
        self, time_value: datetime.datetime, user_id: str = "default", format_str: str = "%Y-%m-%d %H:%M:%S"
    ) -> str:
        """
        为用户格式化时间

        Args:
            time_value: 时间值
            user_id: 用户ID
            format_str: 格式化字符串

        Returns:
            格式化的时间字符串
        """
        with self._lock:
            # 转换到用户时区
            user_time = self.get_user_local_time(user_id, time_value)

            # 格式化
            return user_time.strftime(format_str)

    def get_current_time_in_timezone(self, timezone_name: str) -> datetime.datetime:
        """
        获取指定时区的当前时间

        Args:
            timezone_name: 时区名称

        Returns:
            当前时间
        """
        with self._lock:
            try:
                zone_info = ZoneInfo(timezone_name)
                return datetime.datetime.now(zone_info)
            except Exception as e:
                logger.error("获取时区时间失败: %s", e)
                return datetime.datetime.now()

    def get_timezone_offset(self, timezone_name: str) -> Optional[float]:
        """
        获取时区偏移量

        Args:
            timezone_name: 时区名称

        Returns:
            UTC偏移小时数，失败返回 None
        """
        with self._lock:
            try:
                zone_info = ZoneInfo(timezone_name)
                now = datetime.datetime.now(zone_info)
                offset = now.utcoffset()

                if offset:
                    return offset.total_seconds() / 3600
                return 0.0

            except Exception as e:
                logger.error("获取时区偏移失败: %s", e)
                return None

    def search_timezones(self, query: str) -> List[TimezoneInfo]:
        """
        搜索时区

        Args:
            query: 搜索查询

        Returns:
            匹配的时区信息列表
        """
        with self._lock:
            query_lower = query.lower()
            results = []

            for tz_info in self._timezones.values():
                # 搜索名称、偏移量和描述
                if (
                    query_lower in tz_info.name.lower()
                    or query_lower in tz_info.offset.lower()
                    or query_lower in tz_info.description.lower()
                ):
                    results.append(tz_info)

            return results


# 全局实例管理
_timezone_manager: Optional[TimezoneManager] = None
_manager_lock = threading.Lock()


def get_timezone_manager(config: Dict[str, Any] = None) -> TimezoneManager:
    """
    获取全局时区管理器实例

    Args:
        config: 配置字典

    Returns:
        TimezoneManager 实例
    """
    global _timezone_manager
    if _timezone_manager is None:
        with _manager_lock:
            if _timezone_manager is None:
                _timezone_manager = TimezoneManager(config)
    return _timezone_manager


def init_timezone_manager(config: Dict[str, Any] = None) -> TimezoneManager:
    """
    初始化全局时区管理器

    Args:
        config: 配置字典

    Returns:
        TimezoneManager 实例
    """
    global _timezone_manager
    with _manager_lock:
        if _timezone_manager is not None:
            logger.warning("TimezoneManager 已初始化，将重新创建")

        _timezone_manager = TimezoneManager(config)
        return _timezone_manager


def reset_timezone_manager() -> None:
    """
    重置全局时区管理器
    """
    global _timezone_manager
    with _manager_lock:
        _timezone_manager = None
