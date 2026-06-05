from __future__ import annotations

"""
统一错误处理模块 - 标准化错误管理

功能:
- 错误码定义
- 自定义异常类
- 错误追踪与统计
- 错误恢复策略
- 错误报告生成
"""

from dataclasses import dataclass
import enum
import logging
import threading
import time
import traceback
import typing

from enum import IntEnum
from typing import Optional, Type

# core imports
import asyncio

class ErrorCode(IntEnum):
    """错误码定义"""
    # 通用错误
    UNKNOWN = 0
    INVALID_ARGUMENT = 1001
    INVALID_STATE = 1002
    NOT_FOUND = 1003
    ALREADY_EXISTS = 1004
    PERMISSION_DENIED = 1005
    TIMEOUT = 1006
    RESOURCE_EXHAUSTED = 1007
    
    # 模块错误
    MODULE_LOAD_FAILED = 2001
    MODULE_DEPENDENCY_MISSING = 2002
    MODULE_INIT_FAILED = 2003
    MODULE_START_FAILED = 2004
    MODULE_STOP_FAILED = 2005
    
    # 配置错误
    CONFIG_INVALID = 3001
    CONFIG_MISSING = 3002
    CONFIG_PARSE_ERROR = 3003
    
    # 网络错误
    NETWORK_ERROR = 4001
    CONNECTION_FAILED = 4002
    REQUEST_TIMEOUT = 4003
    RESPONSE_ERROR = 4004
    
    # 认证错误
    AUTH_FAILED = 5001
    TOKEN_EXPIRED = 5002
    TOKEN_INVALID = 5003
    PERMISSION_DENIED_AUTH = 5004
    
    # 数据错误
    DATA_INVALID = 6001
    DATA_NOT_FOUND = 6002
    DATA_CORRUPTED = 6003
    DATA_CONFLICT = 6004
    
    # LLM 错误
    LLM_ERROR = 7001
    LLM_TIMEOUT = 7002
    LLM_RATE_LIMIT = 7003
    LLM_INVALID_RESPONSE = 7004
    
    # 工具错误
    TOOL_ERROR = 8001
    TOOL_NOT_FOUND = 8002
    TOOL_EXECUTION_FAILED = 8003
    TOOL_TIMEOUT = 8004

@dataclass
class ErrorRecord:
    """错误记录"""
    timestamp: float
    code: ErrorCode
    message: str
    module: str
    context: typing.Dict[str, typing.Any] = None
    exception: Optional[str] = None
    stack_trace: Optional[str] = None
    recovery_attempted: bool = False
    recovery_success: bool = False
    
    def __post_init__(self):
        if self.context is None:
            self.context = {}
    
    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "timestamp": self.timestamp,
            "code": self.code.value,
            "message": self.message,
            "module": self.module,
            "context": self.context,
            "exception": self.exception,
            "stack_trace": self.stack_trace,
            "recovery_attempted": self.recovery_attempted,
            "recovery_success": self.recovery_success,
        }

class NeurovaError(Exception):
    """Neurova 基础异常类
    
    所有 Neurova 自定义异常都应该继承此类。
    """
    
    def __init__(
        self,
        code: ErrorCode = ErrorCode.UNKNOWN,
        message: str = "",
        module: str = "",
        context: typing.Dict[str, typing.Any] = None,
        original_exception: Optional[Exception] = None
    ):
        """初始化异常
        
        Args:
            code: 错误码
            message: 错误消息
            module: 发生错误的模块
            context: 错误上下文
            original_exception: 原始异常
        """
        self.code = code
        self.message = message
        self.module = module
        self.context = context or {}
        self.original_exception = original_exception
        super().__init__(message)
    
    def to_record(self) -> ErrorRecord:
        """转换为错误记录
        
        Returns:
            错误记录
        """
        return ErrorRecord(
            timestamp=time.time(),
            code=self.code,
            message=self.message,
            module=self.module,
            context=self.context,
            exception=str(self.original_exception) if self.original_exception else None,
            stack_trace=traceback.format_exc() if self.original_exception else None,
        )

class ModuleLoadError(NeurovaError):
    """模块加载错误"""
    
    def __init__(self, module_name: str, message: str = "", original_exception: Optional[Exception] = None):
        super().__init__(
            code=ErrorCode.MODULE_LOAD_FAILED,
            message=f"模块加载失败: {module_name} - {message}",
            module=module_name,
            original_exception=original_exception
        )

class ModuleDependencyError(NeurovaError):
    """模块依赖错误"""
    
    def __init__(self, module_name: str, dependency: str, original_exception: Optional[Exception] = None):
        super().__init__(
            code=ErrorCode.MODULE_DEPENDENCY_MISSING,
            message=f"模块依赖缺失: {module_name} 依赖 {dependency}",
            module=module_name,
            context={"dependency": dependency},
            original_exception=original_exception
        )

class StateError(NeurovaError):
    """状态错误"""
    
    def __init__(self, message: str, module: str = "", original_exception: Optional[Exception] = None):
        super().__init__(
            code=ErrorCode.INVALID_STATE,
            message=message,
            module=module,
            original_exception=original_exception
        )

class ConfigError(NeurovaError):
    """配置错误"""
    
    def __init__(self, message: str, module: str = "", original_exception: Optional[Exception] = None):
        super().__init__(
            code=ErrorCode.CONFIG_INVALID,
            message=message,
            module=module,
            original_exception=original_exception
        )

class ErrorHandler:
    """
    错误处理器
    
    提供统一的错误处理、记录、恢复和报告功能。
    """
    
    def __init__(self, max_records: int = 10000):
        """初始化错误处理器
        
        Args:
            max_records: 最大错误记录数
        """
        self._records: typing.List[ErrorRecord] = []
        self._max_records = max_records
        self._recovery_strategies: typing.Dict[ErrorCode, typing.Callable] = {}
        self._error_callbacks: typing.List[typing.Callable] = []
        self._stats = {
            "total_errors": 0,
            "by_code": {},
            "by_module": {},
            "recovery_attempts": 0,
            "recovery_successes": 0,
        }
        self._logger = logging.getLogger(__name__)
        self._lock = threading.Lock()
    
    def handle(self, exception: Exception, module: str = "", context: typing.Dict[str, typing.Any] = None) -> ErrorRecord:
        """处理异常
        
        Args:
            exception: 异常对象
            module: 发生错误的模块
            context: 错误上下文
            
        Returns:
            错误记录
        """
        # 如果是 NeurovaError，直接使用其错误码
        if isinstance(exception, NeurovaError):
            code = exception.code
            message = exception.message
            if not module:
                module = exception.module
            if not context:
                context = exception.context
        else:
            code = ErrorCode.UNKNOWN
            message = str(exception)
        
        # 创建错误记录
        record = ErrorRecord(
            timestamp=time.time(),
            code=code,
            message=message,
            module=module,
            context=context or {},
            exception=str(exception),
            stack_trace=traceback.format_exc(),
        )
        
        # 尝试恢复
        recovery_attempted, recovery_success = self._try_recover(exception, code, module)
        record.recovery_attempted = recovery_attempted
        record.recovery_success = recovery_success
        
        # 记录错误
        self._add_record(record)
        
        # 触发回调
        self._trigger_callbacks(record)
        
        return record
    
    def handle_code(self, code: ErrorCode, message: str, module: str = "", context: typing.Dict[str, typing.Any] = None) -> ErrorRecord:
        """处理指定错误码
        
        Args:
            code: 错误码
            message: 错误消息
            module: 发生错误的模块
            context: 错误上下文
            
        Returns:
            错误记录
        """
        record = ErrorRecord(
            timestamp=time.time(),
            code=code,
            message=message,
            module=module,
            context=context or {},
        )
        
        self._add_record(record)
        self._trigger_callbacks(record)
        
        return record
    
    async def safe_execute(self, func: typing.Callable, *args, default=None, module: str = "", **kwargs) -> typing.Any:
        """安全执行函数
        
        Args:
            func: 要执行的函数
            *args: 位置参数
            default: 默认返回值
            module: 模块名称
            **kwargs: 关键字参数
            
        Returns:
            函数执行结果，如果失败则返回默认值
        """
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        except Exception as e:
            self.handle(e, module=module)
            return default
    
    def register_recovery(self, code: ErrorCode, recovery_func: typing.Callable) -> None:
        """注册恢复策略
        
        Args:
            code: 错误码
            recovery_func: 恢复函数
        """
        self._recovery_strategies[code] = recovery_func
    
    def _try_recover(self, exception: Exception, code: ErrorCode, module: str) -> typing.Tuple[bool, bool]:
        """尝试恢复
        
        Args:
            exception: 异常
            code: 错误码
            module: 模块名称
            
        Returns:
            (是否尝试恢复, 是否恢复成功)
        """
        if code not in self._recovery_strategies:
            return False, False
        
        self._stats["recovery_attempts"] += 1
        
        try:
            recovery_func = self._recovery_strategies[code]
            recovery_func(exception, module)
            self._stats["recovery_successes"] += 1
            return True, True
        except Exception as recovery_error:
            self._logger.error(f"恢复策略执行失败: {recovery_error}")
            return True, False
    
    def on_error(self, callback: typing.Callable) -> None:
        """注册错误回调
        
        Args:
            callback: 回调函数
        """
        self._error_callbacks.append(callback)
    
    def remove_error_callback(self, callback: typing.Callable) -> bool:
        """移除错误回调
        
        Args:
            callback: 回调函数
            
        Returns:
            是否移除成功
        """
        if callback in self._error_callbacks:
            self._error_callbacks.remove(callback)
            return True
        return False
    
    def get_records(self, code: Optional[ErrorCode] = None, module: Optional[str] = None, limit: int = 100) -> typing.List[ErrorRecord]:
        """获取错误记录
        
        Args:
            code: 错误码过滤
            module: 模块过滤
            limit: 返回数量限制
            
        Returns:
            错误记录列表
        """
        records = self._records.copy()
        
        if code:
            records = [r for r in records if r.code == code]
        
        if module:
            records = [r for r in records if r.module == module]
        
        return records[-limit:]
    
    def get_stats(self) -> typing.Dict[str, typing.Any]:
        """获取统计信息
        
        Returns:
            统计信息字典
        """
        return {
            "total_errors": self._stats["total_errors"],
            "by_code": dict(self._stats["by_code"]),
            "by_module": dict(self._stats["by_module"]),
            "recovery_attempts": self._stats["recovery_attempts"],
            "recovery_successes": self._stats["recovery_successes"],
            "current_records": len(self._records),
        }
    
    def clear(self) -> None:
        """清空错误记录"""
        with self._lock:
            self._records.clear()
            self._stats = {
                "total_errors": 0,
                "by_code": {},
                "by_module": {},
                "recovery_attempts": 0,
                "recovery_successes": 0,
            }
    
    def generate_report(self, time_range_hours: float = 24.0) -> typing.Dict[str, typing.Any]:
        """生成错误报告
        
        Args:
            time_range_hours: 时间范围（小时）
            
        Returns:
            错误报告
        """
        cutoff_time = time.time() - (time_range_hours * 3600)
        recent_records = [r for r in self._records if r.timestamp >= cutoff_time]
        
        # 按错误码分组
        by_code = {}
        for record in recent_records:
            code_name = record.code.name
            if code_name not in by_code:
                by_code[code_name] = []
            by_code[code_name].append(record.to_dict())
        
        # 按模块分组
        by_module = {}
        for record in recent_records:
            if record.module not in by_module:
                by_module[record.module] = []
            by_module[record.module].append(record.to_dict())
        
        return {
            "time_range_hours": time_range_hours,
            "total_errors": len(recent_records),
            "by_code": by_code,
            "by_module": by_module,
            "recovery_stats": {
                "attempts": self._stats["recovery_attempts"],
                "successes": self._stats["recovery_successes"],
            },
        }
    
    def _add_record(self, record: ErrorRecord) -> None:
        """添加错误记录
        
        Args:
            record: 错误记录
        """
        with self._lock:
            self._records.append(record)
            
            # 如果超过最大记录数，移除最旧的
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
            
            # 更新统计
            self._stats["total_errors"] += 1
            
            code_name = record.code.name
            self._stats["by_code"][code_name] = self._stats["by_code"].get(code_name, 0) + 1
            
            if record.module:
                self._stats["by_module"][record.module] = self._stats["by_module"].get(record.module, 0) + 1
        
        # 记录到日志
        self._logger.error(f"错误 [{record.code.name}] {record.message} (模块: {record.module})")
    
    def _trigger_callbacks(self, record: ErrorRecord) -> None:
        """触发错误回调
        
        Args:
            record: 错误记录
        """
        for callback in self._error_callbacks:
            try:
                callback(record)
            except Exception as e:
                self._logger.error(f"错误回调执行失败: {e}")

"""
获取全局错误处理器
"""
# 全局错误处理器实例
_error_handler: Optional[ErrorHandler] = None

def get_error_handler(max_records: int = 10000) -> ErrorHandler:
    """获取全局错误处理器
    
    Args:
        max_records: 最大错误记录数
        
    Returns:
        错误处理器实例
    """
    global _error_handler
    if _error_handler is None:
        _error_handler = ErrorHandler(max_records=max_records)
    return _error_handler

def reset_error_handler() -> None:
    """重置全局错误处理器（主要用于测试）"""
    global _error_handler
    _error_handler = None
