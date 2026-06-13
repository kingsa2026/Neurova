"""
Tool History Tracker v1.0.0 — 工具执行历史追踪器

职责:
- 接收并存储 ToolExecutionEntry 记录
- 提供按时间/工具名/成功状态等维度的查询
- 计算工具使用统计和异常检测
- 作为 MetaCognition 和 Tool Layer 之间的数据桥梁

隔离层级: 每个 MetaCognition 实例持有一个独立的 ToolHistoryTracker
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from neurova.tool_layers.tool_logger import ToolExecutionEntry

logger = logging.getLogger(__name__)


class AnomalyType(str, Enum):
    """异常类型"""

    HIGH_FAILURE_RATE = "high_failure_rate"
    SLOW_EXECUTION = "slow_execution"
    UNUSUAL_PATTERN = "unusual_pattern"
    TIMEOUT_SPIKE = "timeout_spike"
    ERROR_CLUSTER = "error_cluster"


@dataclass
class ToolUsageStats:
    """工具使用统计"""

    tool_name: str
    total_calls: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_duration_ms: float = 0.0
    min_duration_ms: float = float("inf")
    max_duration_ms: float = 0.0
    last_used: float = 0.0
    first_used: float = 0.0
    error_types: Dict[str, int] = field(default_factory=dict)
    param_patterns: Dict[str, int] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_calls == 0:
            return 0.0
        return self.success_count / self.total_calls

    @property
    def failure_rate(self) -> float:
        """失败率"""
        return 1.0 - self.success_rate

    @property
    def avg_duration_ms(self) -> float:
        """平均耗时"""
        if self.total_calls == 0:
            return 0.0
        return self.total_duration_ms / self.total_calls

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "tool_name": self.tool_name,
            "total_calls": self.total_calls,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_duration_ms": self.total_duration_ms,
            "min_duration_ms": self.min_duration_ms if self.min_duration_ms != float("inf") else 0,
            "max_duration_ms": self.max_duration_ms,
            "last_used": self.last_used,
            "first_used": self.first_used,
            "success_rate": self.success_rate,
            "failure_rate": self.failure_rate,
            "avg_duration_ms": self.avg_duration_ms,
            "error_types": self.error_types,
            "param_patterns": self.param_patterns,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolUsageStats":
        """从字典创建"""
        return cls(
            tool_name=data["tool_name"],
            total_calls=data.get("total_calls", 0),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
            total_duration_ms=data.get("total_duration_ms", 0.0),
            min_duration_ms=data.get("min_duration_ms", 0.0),
            max_duration_ms=data.get("max_duration_ms", 0.0),
            last_used=data.get("last_used", 0.0),
            first_used=data.get("first_used", 0.0),
            error_types=data.get("error_types", {}),
            param_patterns=data.get("param_patterns", {}),
        )


@dataclass
class ToolAnomaly:
    """工具异常记录"""

    tool_name: str
    anomaly_type: AnomalyType
    severity: float  # 0.0-1.0
    description: str
    detected_at: float = field(default_factory=time.time)
    context: Dict[str, Any] = field(default_factory=dict)
    related_entries: List[ToolExecutionEntry] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "tool_name": self.tool_name,
            "anomaly_type": self.anomaly_type.value,
            "severity": self.severity,
            "description": self.description,
            "detected_at": self.detected_at,
            "context": self.context,
            "related_entries_count": len(self.related_entries),
        }


class ToolHistoryTracker:
    """
    工具执行历史追踪器

    功能：
    1. 记录和存储工具执行历史
    2. 提供多维度查询
    3. 计算使用统计
    4. 检测异常模式
    """

    def __init__(self, max_history: int = 10000, anomaly_threshold: float = 0.3):
        """
        初始化追踪器

        Args:
            max_history: 最大历史记录数
            anomaly_threshold: 异常检测阈值
        """
        self.max_history = max_history
        self.anomaly_threshold = anomaly_threshold

        # 历史记录存储（按时间排序）
        self._history: List[ToolExecutionEntry] = []

        # 工具使用统计
        self._stats: Dict[str, ToolUsageStats] = {}

        # 异常记录
        self._anomalies: List[ToolAnomaly] = []

        # 索引结构
        self._by_tool: Dict[str, List[int]] = defaultdict(list)  # tool_name -> indices
        self._by_user: Dict[str, List[int]] = defaultdict(list)  # user_id -> indices
        self._by_session: Dict[str, List[int]] = defaultdict(list)  # session_id -> indices
        self._failures: List[int] = []  # 失败记录索引

        # 时间窗口（用于异常检测）
        self._time_window = 3600  # 1小时
        self._recent_failures: Dict[str, List[float]] = defaultdict(list)

        logger.info("ToolHistoryTracker initialized: max_history=%s", max_history)

    def record(self, entry: ToolExecutionEntry) -> None:
        """
        记录工具执行

        Args:
            entry: 工具执行条目
        """
        # 添加到历史记录
        index = len(self._history)
        self._history.append(entry)

        # 更新索引
        self._by_tool[entry.tool_name].append(index)
        if entry.user_id:
            self._by_user[entry.user_id].append(index)
        if entry.session_id:
            self._by_session[entry.session_id].append(index)

        if not entry.success:
            self._failures.append(index)
            self._recent_failures[entry.tool_name].append(entry.timestamp)

        # 更新统计
        self._update_stats(entry)

        # 检查异常
        self._check_anomalies(entry)

        # 清理旧记录
        if len(self._history) > self.max_history:
            self._cleanup_old_entries()

        logger.debug("Recorded tool execution: %s", entry.tool_name)

    def record_batch(self, entries: List[ToolExecutionEntry]) -> None:
        """
        批量记录工具执行

        Args:
            entries: 工具执行条目列表
        """
        for entry in entries:
            self.record(entry)

    def get_recent(self, limit: int = 100, tool_name: Optional[str] = None) -> List[ToolExecutionEntry]:
        """
        获取最近的执行记录

        Args:
            limit: 返回数量限制
            tool_name: 工具名称过滤

        Returns:
            执行记录列表
        """
        if tool_name:
            indices = self._by_tool.get(tool_name, [])
            entries = [self._history[i] for i in indices if i < len(self._history)]
            return entries[-limit:]

        return self._history[-limit:]

    def get_by_tool(self, tool_name: str, limit: Optional[int] = None) -> List[ToolExecutionEntry]:
        """
        按工具名获取执行记录

        Args:
            tool_name: 工具名称
            limit: 返回数量限制

        Returns:
            执行记录列表
        """
        indices = self._by_tool.get(tool_name, [])
        entries = [self._history[i] for i in indices if i < len(self._history)]

        if limit:
            return entries[-limit:]
        return entries

    def get_failures(self, limit: int = 100, tool_name: Optional[str] = None) -> List[ToolExecutionEntry]:
        """
        获取失败记录

        Args:
            limit: 返回数量限制
            tool_name: 工具名称过滤

        Returns:
            失败记录列表
        """
        if tool_name:
            tool_indices = self._by_tool.get(tool_name, [])
            failure_indices = [i for i in self._failures if i in tool_indices]
            entries = [self._history[i] for i in failure_indices if i < len(self._history)]
            return entries[-limit:]

        entries = [self._history[i] for i in self._failures if i < len(self._history)]
        return entries[-limit:]

    def get_since(self, timestamp: float, tool_name: Optional[str] = None) -> List[ToolExecutionEntry]:
        """
        获取指定时间之后的记录

        Args:
            timestamp: 时间戳
            tool_name: 工具名称过滤

        Returns:
            执行记录列表
        """
        if tool_name:
            indices = self._by_tool.get(tool_name, [])
            entries = [
                self._history[i] for i in indices if i < len(self._history) and self._history[i].timestamp >= timestamp
            ]
        else:
            entries = [e for e in self._history if e.timestamp >= timestamp]

        return entries

    def get_by_source(self, source_type: str, source_id: str, limit: Optional[int] = None) -> List[ToolExecutionEntry]:
        """
        按来源获取记录

        Args:
            source_type: 来源类型（user/session）
            source_id: 来源ID
            limit: 返回数量限制

        Returns:
            执行记录列表
        """
        if source_type == "user":
            indices = self._by_user.get(source_id, [])
        elif source_type == "session":
            indices = self._by_session.get(source_id, [])
        else:
            return []

        entries = [self._history[i] for i in indices if i < len(self._history)]

        if limit:
            return entries[-limit:]
        return entries

    def total_entries(self) -> int:
        """获取总记录数"""
        return len(self._history)

    def get_usage_stats(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """
        获取使用统计

        Args:
            tool_name: 工具名称，如果为 None 则返回所有工具的统计

        Returns:
            统计信息字典
        """
        if tool_name:
            stats = self._stats.get(tool_name)
            if stats:
                return stats.to_dict()
            return {}

        return {name: stats.to_dict() for name, stats in self._stats.items()}

    def get_tool_stats(self, tool_name: str) -> Optional[ToolUsageStats]:
        """
        获取特定工具的统计

        Args:
            tool_name: 工具名称

        Returns:
            工具使用统计对象
        """
        return self._stats.get(tool_name)

    def get_top_tools(self, limit: int = 10, sort_by: str = "total_calls") -> List[Dict[str, Any]]:
        """
        获取使用最多的工具

        Args:
            limit: 返回数量限制
            sort_by: 排序字段（total_calls/avg_duration_ms/success_rate）

        Returns:
            工具统计列表
        """
        stats_list = []
        for stats in self._stats.values():
            stats_dict = stats.to_dict()
            stats_list.append(stats_dict)

        # 排序
        if sort_by == "total_calls":
            stats_list.sort(key=lambda x: x["total_calls"], reverse=True)
        elif sort_by == "avg_duration_ms":
            stats_list.sort(key=lambda x: x["avg_duration_ms"], reverse=True)
        elif sort_by == "success_rate":
            stats_list.sort(key=lambda x: x["success_rate"], reverse=True)

        return stats_list[:limit]

    def get_degraded_tools(self, threshold: float = 0.7) -> List[Dict[str, Any]]:
        """
        获取性能下降的工具

        Args:
            threshold: 成功率阈值，低于此值认为性能下降

        Returns:
            性能下降的工具列表
        """
        degraded = []
        for stats in self._stats.values():
            if stats.total_calls >= 10 and stats.success_rate < threshold:
                degraded.append(
                    {
                        "tool_name": stats.tool_name,
                        "success_rate": stats.success_rate,
                        "total_calls": stats.total_calls,
                        "avg_duration_ms": stats.avg_duration_ms,
                    }
                )

        return degraded

    def detect_anomalies(self, time_window: Optional[int] = None) -> List[ToolAnomaly]:
        """
        检测异常

        Args:
            time_window: 时间窗口（秒），如果为 None 则使用默认值

        Returns:
            异常列表
        """
        if time_window is None:
            time_window = self._time_window

        current_time = time.time()
        anomalies = []

        # 检查每个工具的异常
        for tool_name, stats in self._stats.items():
            # 检查高失败率
            if stats.total_calls >= 5 and stats.failure_rate > self.anomaly_threshold:
                anomaly = ToolAnomaly(
                    tool_name=tool_name,
                    anomaly_type=AnomalyType.HIGH_FAILURE_RATE,
                    severity=stats.failure_rate,
                    description=f"High failure rate: {stats.failure_rate * 100:.2f}%%",
                    context={
                        "total_calls": stats.total_calls,
                        "failure_count": stats.failure_count,
                        "success_rate": stats.success_rate,
                    },
                )
                anomalies.append(anomaly)

            # 检查慢执行
            if stats.total_calls >= 5:
                avg_duration = stats.avg_duration_ms
                if avg_duration > 10000:  # 10秒
                    severity = min(avg_duration / 30000, 1.0)  # 30秒为最高严重度
                    anomaly = ToolAnomaly(
                        tool_name=tool_name,
                        anomaly_type=AnomalyType.SLOW_EXECUTION,
                        severity=severity,
                        description=f"Slow execution: {avg_duration:.0f}ms average",
                        context={"avg_duration_ms": avg_duration, "max_duration_ms": stats.max_duration_ms},
                    )
                    anomalies.append(anomaly)

            # 检查失败率突增
            recent_failures = self._recent_failures.get(tool_name, [])
            recent_failures = [t for t in recent_failures if current_time - t < time_window]

            if len(recent_failures) >= 3:
                # 计算近期失败率
                recent_total = len(
                    [e for e in self._history if e.tool_name == tool_name and current_time - e.timestamp < time_window]
                )

                if recent_total > 0:
                    recent_failure_rate = len(recent_failures) / recent_total
                    if recent_failure_rate > self.anomaly_threshold * 1.5:
                        anomaly = ToolAnomaly(
                            tool_name=tool_name,
                            anomaly_type=AnomalyType.TIMEOUT_SPIKE,
                            severity=recent_failure_rate,
                            description=f"Recent failure spike: {recent_failure_rate * 100:.2f}%% in last hour",
                            context={
                                "recent_failures": len(recent_failures),
                                "recent_total": recent_total,
                                "time_window": time_window,
                            },
                        )
                        anomalies.append(anomaly)

        # 存储异常
        self._anomalies.extend(anomalies)

        return anomalies

    def find_tool_pairs(self, min_support: int = 3, min_confidence: float = 0.5) -> List[Tuple[str, str, float]]:
        """
        发现工具使用模式（工具对）

        Args:
            min_support: 最小支持度（共现次数）
            min_confidence: 最小置信度

        Returns:
            工具对列表 [(tool1, tool2, confidence), ...]
        """
        # 按会话分组
        session_tools: Dict[str, List[str]] = defaultdict(list)
        for entry in self._history:
            if entry.session_id:
                session_tools[entry.session_id].append(entry.tool_name)

        # 统计工具对共现
        pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)
        tool_counts: Dict[str, int] = defaultdict(int)

        for session_id, tools in session_tools.items():
            # 去重并排序
            unique_tools = sorted(set(tools))

            # 统计单个工具
            for tool in unique_tools:
                tool_counts[tool] += 1

            # 统计工具对
            for i in range(len(unique_tools)):
                for j in range(i + 1, len(unique_tools)):
                    pair = (unique_tools[i], unique_tools[j])
                    pair_counts[pair] += 1

        # 计算置信度
        pairs = []
        for (tool1, tool2), count in pair_counts.items():
            if count >= min_support:
                # 计算置信度：P(tool2|tool1) 和 P(tool1|tool2)
                conf1 = count / tool_counts[tool1] if tool_counts[tool1] > 0 else 0
                conf2 = count / tool_counts[tool2] if tool_counts[tool2] > 0 else 0
                avg_confidence = (conf1 + conf2) / 2

                if avg_confidence >= min_confidence:
                    pairs.append((tool1, tool2, avg_confidence))

        # 按置信度排序
        pairs.sort(key=lambda x: x[2], reverse=True)

        return pairs

    def clear(self) -> None:
        """清除所有历史记录"""
        self._history.clear()
        self._stats.clear()
        self._anomalies.clear()
        self._by_tool.clear()
        self._by_user.clear()
        self._by_session.clear()
        self._failures.clear()
        self._recent_failures.clear()

        logger.info("ToolHistoryTracker cleared")

    def to_snapshot(self) -> Dict[str, Any]:
        """
        创建快照

        Returns:
            快照字典
        """
        return {
            "timestamp": time.time(),
            "total_entries": len(self._history),
            "stats": self.get_usage_stats(),
            "anomalies": [a.to_dict() for a in self._anomalies[-100:]],  # 最近100个异常
            "top_tools": self.get_top_tools(limit=10),
            "degraded_tools": self.get_degraded_tools(),
        }

    def _update_stats(self, entry: ToolExecutionEntry) -> None:
        """更新统计信息"""
        tool_name = entry.tool_name

        if tool_name not in self._stats:
            self._stats[tool_name] = ToolUsageStats(tool_name=tool_name)

        stats = self._stats[tool_name]
        stats.total_calls += 1
        stats.total_duration_ms += entry.duration_ms

        if entry.success:
            stats.success_count += 1
        else:
            stats.failure_count += 1
            # 记录错误类型
            if entry.error:
                error_type = entry.error[:50]  # 截断错误信息
                stats.error_types[error_type] = stats.error_types.get(error_type, 0) + 1

        # 更新时间
        if stats.first_used == 0 or entry.timestamp < stats.first_used:
            stats.first_used = entry.timestamp
        if entry.timestamp > stats.last_used:
            stats.last_used = entry.timestamp

        # 更新耗时
        if entry.duration_ms < stats.min_duration_ms:
            stats.min_duration_ms = entry.duration_ms
        if entry.duration_ms > stats.max_duration_ms:
            stats.max_duration_ms = entry.duration_ms

        # 更新参数模式
        if entry.params:
            param_keys = tuple(sorted(entry.params.keys()))
            pattern = str(param_keys)
            stats.param_patterns[pattern] = stats.param_patterns.get(pattern, 0) + 1

    def _check_anomalies(self, entry: ToolExecutionEntry) -> None:
        """检查单条记录的异常"""
        # 检查超时
        if entry.duration_ms > 30000:  # 30秒
            anomaly = ToolAnomaly(
                tool_name=entry.tool_name,
                anomaly_type=AnomalyType.SLOW_EXECUTION,
                severity=min(entry.duration_ms / 60000, 1.0),  # 60秒为最高严重度
                description=f"Slow execution: {entry.duration_ms:.0f}ms",
                context={"duration_ms": entry.duration_ms},
                related_entries=[entry],
            )
            self._anomalies.append(anomaly)

    def _cleanup_old_entries(self) -> None:
        """清理旧记录"""
        # 保留最近的记录
        keep_count = self.max_history * 0.8  # 保留80%
        remove_count = len(self._history) - int(keep_count)

        if remove_count <= 0:
            return

        # 移除旧记录
        self._history = self._history[remove_count:]

        # 重建索引
        self._rebuild_indices()

        logger.info("Cleaned up %s old entries", remove_count)

    def _rebuild_indices(self) -> None:
        """重建索引"""
        self._by_tool.clear()
        self._by_user.clear()
        self._by_session.clear()
        self._failures.clear()

        for i, entry in enumerate(self._history):
            self._by_tool[entry.tool_name].append(i)
            if entry.user_id:
                self._by_user[entry.user_id].append(i)
            if entry.session_id:
                self._by_session[entry.session_id].append(i)
            if not entry.success:
                self._failures.append(i)


# 便捷函数
def create_tool_history_tracker(max_history: int = 10000, anomaly_threshold: float = 0.3) -> ToolHistoryTracker:
    """
    创建工具历史追踪器

    Args:
        max_history: 最大历史记录数
        anomaly_threshold: 异常检测阈值

    Returns:
        ToolHistoryTracker 实例
    """
    return ToolHistoryTracker(max_history=max_history, anomaly_threshold=anomaly_threshold)
