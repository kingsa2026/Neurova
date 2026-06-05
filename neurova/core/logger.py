from __future__ import annotations

"""
统一日志管理模块 - 结构化日志系统

功能:
- 多级别日志 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
- 模块级日志过滤
- 结构化日志输出 (JSON)
- 日志轮转
- 日志聚合统计
"""

import collections
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
import json
import logging
import os
from pathlib import Path
import time
import typing
from typing import Deque, Dict, List, Optional, Any

# 定义 LogLevel 枚举
class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

def __annotate__(*args, **kwargs):
    """TODO: Auto-restored from .pyc, needs implementation"""
    pass

def get_logger(name: str = "neurova", level: int = logging.DEBUG) -> logging.Logger:
    """
    获取指定模块的记录器

    参数:
        name: 记录器名称（通常是模块的 __name__）
        level: 日志级别

    返回:
        配置好的 logging.Logger 实例
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(level)
        # 控制台 handler
        handler = logging.StreamHandler()
        handler.setLevel(level)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

def __annotate__(*args, **kwargs):
    """TODO: Auto-restored from .pyc, needs implementation"""
    pass

def _sanitize_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """过滤敏感字段
    
    Args:
        context: 原始上下文
        
    Returns:
        过滤后的上下文
    """
    sensitive_keys = {"password", "token", "secret", "api_key", "apikey", "auth"}
    sanitized = {}
    for key, value in context.items():
        if any(sensitive in key.lower() for sensitive in sensitive_keys):
            sanitized[key] = "***"
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_context(value)
        else:
            sanitized[key] = value
    return sanitized

@dataclass
class LogEntry:
    """日志条目"""
    timestamp: float
    level: LogLevel
    module: str
    message: str
    context: Dict[str, Any] = None
    exception: Optional[str] = None
    
    def __post_init__(self):
        if self.context is None:
            self.context = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "timestamp": self.timestamp,
            "level": self.level.value,
            "module": self.module,
            "message": self.message,
            "context": self.context,
            "exception": self.exception,
        }

class LogManager:
    """
    日志管理器
    
    提供结构化日志记录、模块级过滤、日志轮转和统计功能。
    """
    
    def __init__(self, max_entries: int = 10000, default_level: LogLevel = LogLevel.INFO):
        """初始化日志管理器
        
        Args:
            max_entries: 最大日志条目数
            default_level: 默认日志级别
        """
        self._entries: Deque[LogEntry] = collections.deque(maxlen=max_entries)
        self._module_levels: Dict[str, LogLevel] = {}
        self._default_level = default_level
        self._stats = {
            "total_logs": 0,
            "by_level": {level.value: 0 for level in LogLevel},
            "by_module": defaultdict(int),
        }
        self._logger = logging.getLogger(__name__)
    
    def set_level(self, module: str, level: LogLevel) -> None:
        """设置模块日志级别
        
        Args:
            module: 模块名称
            level: 日志级别
        """
        self._module_levels[module] = level
    
    def set_default_level(self, level: LogLevel) -> None:
        """设置默认日志级别
        
        Args:
            level: 日志级别
        """
        self._default_level = level
    
    def _should_log(self, module: str, level: LogLevel) -> bool:
        """检查是否应该记录日志
        
        Args:
            module: 模块名称
            level: 日志级别
            
        Returns:
            是否应该记录
        """
        module_level = self._module_levels.get(module, self._default_level)
        level_order = [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL]
        return level_order.index(level) >= level_order.index(module_level)
    
    def log(self, level: LogLevel, module: str, message: str, context: Optional[Dict[str, Any]] = None, exception: Optional[str] = None) -> None:
        """记录日志
        
        Args:
            level: 日志级别
            module: 模块名称
            message: 日志消息
            context: 上下文信息
            exception: 异常信息
        """
        if not self._should_log(module, level):
            return
        
        sanitized_context = _sanitize_context(context) if context else {}
        
        entry = LogEntry(
            timestamp=time.time(),
            level=level,
            module=module,
            message=message,
            context=sanitized_context,
            exception=exception,
        )
        
        self._entries.append(entry)
        self._stats["total_logs"] += 1
        self._stats["by_level"][level.value] += 1
        self._stats["by_module"][module] += 1
        
        # 同步到标准日志
        self._sync_to_logging(entry)
    
    def debug(self, module: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """记录 DEBUG 级别日志"""
        self.log(LogLevel.DEBUG, module, message, context)
    
    def info(self, module: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """记录 INFO 级别日志"""
        self.log(LogLevel.INFO, module, message, context)
    
    def warning(self, module: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """记录 WARNING 级别日志"""
        self.log(LogLevel.WARNING, module, message, context)
    
    def error(self, module: str, message: str, context: Optional[Dict[str, Any]] = None, exception: Optional[str] = None) -> None:
        """记录 ERROR 级别日志"""
        self.log(LogLevel.ERROR, module, message, context, exception)
    
    def critical(self, module: str, message: str, context: Optional[Dict[str, Any]] = None, exception: Optional[str] = None) -> None:
        """记录 CRITICAL 级别日志"""
        self.log(LogLevel.CRITICAL, module, message, context, exception)
    
    def _sync_to_logging(self, entry: LogEntry) -> None:
        """同步到标准日志
        
        Args:
            entry: 日志条目
        """
        level_map = {
            LogLevel.DEBUG: logging.DEBUG,
            LogLevel.INFO: logging.INFO,
            LogLevel.WARNING: logging.WARNING,
            LogLevel.ERROR: logging.ERROR,
            LogLevel.CRITICAL: logging.CRITICAL,
        }
        
        logger = logging.getLogger(entry.module)
        log_level = level_map.get(entry.level, logging.INFO)
        
        extra_info = ""
        if entry.context:
            extra_info = f" | {json.dumps(entry.context, ensure_ascii=False)}"
        
        if entry.exception:
            logger.log(log_level, f"{entry.message}{extra_info}", exc_info=True)
        else:
            logger.log(log_level, f"{entry.message}{extra_info}")
    
    def get_entries(self, module: Optional[str] = None, level: Optional[LogLevel] = None, limit: int = 100) -> List[LogEntry]:
        """获取日志条目
        
        Args:
            module: 模块名称过滤
            level: 日志级别过滤
            limit: 返回数量限制
            
        Returns:
            日志条目列表
        """
        entries = list(self._entries)
        
        if module:
            entries = [e for e in entries if e.module == module]
        
        if level:
            entries = [e for e in entries if e.level == level]
        
        return entries[-limit:]
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息
        
        Returns:
            统计信息字典
        """
        return {
            "total_logs": self._stats["total_logs"],
            "by_level": dict(self._stats["by_level"]),
            "by_module": dict(self._stats["by_module"]),
            "current_entries": len(self._entries),
        }
    
    def export_json(self, filepath: str) -> None:
        """导出日志到JSON文件
        
        Args:
            filepath: 文件路径
        """
        entries = [entry.to_dict() for entry in self._entries]
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
    
    def clear(self) -> None:
        """清空日志"""
        self._entries.clear()
        self._stats = {
            "total_logs": 0,
            "by_level": {level.value: 0 for level in LogLevel},
            "by_module": defaultdict(int),
        }
    
    def rotate(self, max_age_hours: float = 24.0) -> int:
        """轮转日志
        
        Args:
            max_age_hours: 最大保留时间（小时）
            
        Returns:
            移除的日志条目数
        """
        cutoff_time = time.time() - (max_age_hours * 3600)
        original_count = len(self._entries)
        
        # 过滤掉过期的条目
        self._entries = collections.deque(
            [entry for entry in self._entries if entry.timestamp >= cutoff_time],
            maxlen=self._entries.maxlen
        )
        
        removed_count = original_count - len(self._entries)
        if removed_count > 0:
            self._logger.info(f"日志轮转: 移除了 {removed_count} 条过期日志")
        
        return removed_count
    
    def entry_count(self) -> int:
        """获取日志条目数量
        
        Returns:
            日志条目数量
        """
        return len(self._entries)

def __annotate__(*args, **kwargs):
    """TODO: Auto-restored from .pyc, needs implementation"""
    pass

"""
获取全局日志管理器
"""
# 全局日志管理器实例
_log_manager: Optional[LogManager] = None

def get_log_manager(max_entries: int = 10000, default_level: LogLevel = LogLevel.INFO) -> LogManager:
    """获取全局日志管理器
    
    Args:
        max_entries: 最大日志条目数
        default_level: 默认日志级别
        
    Returns:
        日志管理器实例
    """
    global _log_manager
    if _log_manager is None:
        _log_manager = LogManager(max_entries=max_entries, default_level=default_level)
    return _log_manager

def reset_log_manager() -> None:
    """重置全局日志管理器（主要用于测试）"""
    global _log_manager
    _log_manager = None
