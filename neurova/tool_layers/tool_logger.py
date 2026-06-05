"""
Tool Execution Logger v1.0.0 — 结构化工具执行日志

职责:
- 以 JSON Lines 格式记录每次工具调用
- 支持缓冲写入、自动刷新
- 支持查询和统计
- 为 Phase 1-3 的元认知分析和模式挖掘提供数据基础
"""

from dataclasses import dataclass, field
import datetime
import json
import logging
from pathlib import Path
import time
import typing

logger = logging.getLogger(__name__)


@dataclass
class ToolExecutionEntry:
    """工具执行条目"""
    tool_name: str
    params: typing.Dict[str, typing.Any]
    result: typing.Dict[str, typing.Any]
    duration_ms: float
    success: bool
    error: typing.Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    user_id: str = ""
    session_id: str = ""
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)
    
    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        data = {
            "tool_name": self.tool_name,
            "params": self.params,
            "result": self.result,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "metadata": self.metadata
        }
        
        if self.error:
            data["error"] = self.error
        
        return data
    
    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)
    
    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> 'ToolExecutionEntry':
        """从字典创建"""
        return cls(
            tool_name=data["tool_name"],
            params=data["params"],
            result=data["result"],
            duration_ms=data["duration_ms"],
            success=data["success"],
            error=data.get("error"),
            timestamp=data.get("timestamp", time.time()),
            user_id=data.get("user_id", ""),
            session_id=data.get("session_id", ""),
            metadata=data.get("metadata", {})
        )


class ToolExecutionLogger:
    """
    工具执行日志器
    
    功能：
    1. 以 JSON Lines 格式记录工具执行
    2. 支持缓冲写入，减少 I/O 操作
    3. 支持自动刷新和手动刷新
    4. 支持按时间、工具名称查询
    5. 支持统计信息
    """
    
    def __init__(
        self, 
        log_file: str = "tool_execution.jsonl",
        buffer_size: int = 100,
        auto_flush: bool = True
    ):
        """
        初始化日志器
        
        参数:
            log_file: 日志文件路径
            buffer_size: 缓冲区大小
            auto_flush: 是否自动刷新
        """
        self._log_file = log_file
        self._buffer_size = buffer_size
        self._auto_flush = auto_flush
        
        # 缓冲区
        self._buffer: typing.List[ToolExecutionEntry] = []
        
        # 统计信息
        self._stats = {
            "total_executions": 0,
            "success_count": 0,
            "failure_count": 0,
            "total_duration_ms": 0.0,
            "tool_counts": {}
        }
        
        # 确保日志目录存在
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"ToolExecutionLogger initialized: {log_file}")
    
    def log(self, entry: ToolExecutionEntry) -> None:
        """
        记录工具执行
        
        参数:
            entry: 工具执行条目
        """
        # 添加到缓冲区
        self._buffer.append(entry)
        
        # 更新统计信息
        self._update_stats(entry)
        
        # 检查是否需要自动刷新
        if self._auto_flush and len(self._buffer) >= self._buffer_size:
            self.flush()
    
    def flush(self) -> None:
        """刷新缓冲区到文件"""
        if not self._buffer:
            return
        
        try:
            # 以追加模式打开文件
            with open(self._log_file, 'a', encoding='utf-8') as f:
                for entry in self._buffer:
                    f.write(entry.to_json() + '\n')
            
            # 清空缓冲区
            self._buffer.clear()
            
            logger.debug(f"Flushed {len(self._buffer)} entries to {self._log_file}")
            
        except Exception as e:
            logger.error(f"Failed to flush log entries: {e}")
    
    def query_recent(
        self, 
        limit: int = 100,
        tool_name: typing.Optional[str] = None,
        start_time: typing.Optional[float] = None,
        end_time: typing.Optional[float] = None
    ) -> typing.List[ToolExecutionEntry]:
        """
        查询最近日志
        
        参数:
            limit: 返回条目数量限制
            tool_name: 工具名称过滤
            start_time: 开始时间戳
            end_time: 结束时间戳
            
        返回:
            符合条件的条目列表
        """
        # 先刷新缓冲区
        self.flush()
        
        # 读取日志文件
        entries = []
        
        try:
            with open(self._log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        data = json.loads(line)
                        entry = ToolExecutionEntry.from_dict(data)
                        
                        # 应用过滤器
                        if tool_name and entry.tool_name != tool_name:
                            continue
                        
                        if start_time and entry.timestamp < start_time:
                            continue
                        
                        if end_time and entry.timestamp > end_time:
                            continue
                        
                        entries.append(entry)
                        
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON line: {line}")
                        continue
        
        except FileNotFoundError:
            logger.warning(f"Log file not found: {self._log_file}")
            return []
        
        # 按时间戳排序（最新的在前）
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        
        # 返回指定数量的条目
        return entries[:limit]
    
    def get_stats(self) -> typing.Dict[str, typing.Any]:
        """
        获取统计信息
        
        返回:
            统计信息字典
        """
        # 先刷新缓冲区
        self.flush()
        
        # 计算平均耗时
        avg_duration = 0.0
        if self._stats["total_executions"] > 0:
            avg_duration = self._stats["total_duration_ms"] / self._stats["total_executions"]
        
        return {
            "total_executions": self._stats["total_executions"],
            "success_count": self._stats["success_count"],
            "failure_count": self._stats["failure_count"],
            "avg_duration_ms": avg_duration,
            "tool_counts": self._stats["tool_counts"].copy()
        }
    
    def close(self) -> None:
        """关闭日志器"""
        # 刷新缓冲区
        self.flush()
        
        logger.info(f"ToolExecutionLogger closed: {self._log_file}")
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()
        return False
    
    def __del__(self):
        """析构函数"""
        try:
            self.close()
        except:
            pass
    
    def _update_stats(self, entry: ToolExecutionEntry) -> None:
        """
        更新统计信息
        
        参数:
            entry: 工具执行条目
        """
        self._stats["total_executions"] += 1
        self._stats["total_duration_ms"] += entry.duration_ms
        
        if entry.success:
            self._stats["success_count"] += 1
        else:
            self._stats["failure_count"] += 1
        
        # 更新工具计数
        tool_name = entry.tool_name
        if tool_name not in self._stats["tool_counts"]:
            self._stats["tool_counts"][tool_name] = 0
        self._stats["tool_counts"][tool_name] += 1