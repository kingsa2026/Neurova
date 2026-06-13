"""
日志级别定义 - 独立文件避免循环导入
"""

from enum import IntEnum


class LogLevel(IntEnum):
    """日志级别"""

    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50
