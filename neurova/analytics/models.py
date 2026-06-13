from __future__ import annotations

"""
Neurova 数据分析模块 - 数据模型
定义分析数据结构和类型
"""

import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class MetricType(Enum):
    """指标类型"""

    COUNTER = "counter"  # 计数器，只增不减
    GAUGE = "gauge"  # 仪表盘，可增可减
    HISTOGRAM = "histogram"  # 直方图
    SUMMARY = "summary"  # 摘要
    RATE = "rate"  # 速率
    PERCENTAGE = "percentage"  # 百分比


class AgentStatus(Enum):
    """Agent状态"""

    ACTIVE = "active"
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    OFFLINE = "offline"
    STARTING = "starting"
    STOPPING = "stopping"


class TaskStatus(Enum):
    """任务状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class TimeSeriesPoint:
    """时间序列数据点"""

    timestamp: float
    value: float
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimeSeriesPoint":
        """从字典创建"""
        return cls(**data)


@dataclass
class AgentMetrics:
    """Agent指标"""

    agent_id: str
    agent_name: str
    status: AgentStatus
    uptime_seconds: float
    total_requests: int
    successful_requests: int
    failed_requests: int
    average_response_time: float
    memory_usage_mb: float
    cpu_usage_percent: float
    active_tasks: int
    queued_tasks: int
    last_active_at: Optional[float] = None
    created_at: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
        if self.last_active_at is None:
            self.last_active_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["status"] = self.status.value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentMetrics":
        """从字典创建"""
        data = data.copy()
        data["status"] = AgentStatus(data["status"])
        return cls(**data)

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests

    @property
    def error_rate(self) -> float:
        """错误率"""
        if self.total_requests == 0:
            return 0.0
        return self.failed_requests / self.total_requests


@dataclass
class UserMetrics:
    """用户指标"""

    user_id: str
    username: str
    total_sessions: int
    total_messages: int
    average_session_duration: float
    total_tokens_used: int
    total_cost: float
    favorite_agent_id: Optional[str] = None
    last_active_at: Optional[float] = None
    created_at: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
        if self.last_active_at is None:
            self.last_active_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserMetrics":
        """从字典创建"""
        return cls(**data)


@dataclass
class TaskMetrics:
    """任务指标"""

    task_id: str
    task_type: str
    status: TaskStatus
    agent_id: str
    user_id: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration_seconds: Optional[float] = None
    tokens_used: int = 0
    cost: float = 0.0
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.start_time is None:
            self.start_time = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["status"] = self.status.value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskMetrics":
        """从字典创建"""
        data = data.copy()
        data["status"] = TaskStatus(data["status"])
        return cls(**data)

    def complete(self, tokens_used: int = 0, cost: float = 0.0):
        """完成任务"""
        self.status = TaskStatus.COMPLETED
        self.end_time = time.time()
        self.duration_seconds = self.end_time - self.start_time
        self.tokens_used = tokens_used
        self.cost = cost

    def fail(self, error_message: str):
        """任务失败"""
        self.status = TaskStatus.FAILED
        self.end_time = time.time()
        self.duration_seconds = self.end_time - self.start_time
        self.error_message = error_message


@dataclass
class DashboardStats:
    """仪表盘统计"""

    total_agents: int
    active_agents: int
    total_users: int
    active_users: int
    total_requests: int
    requests_per_minute: float
    average_response_time: float
    error_rate: float
    total_tokens_used: int
    total_cost: float
    uptime_seconds: float
    timestamp: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DashboardStats":
        """从字典创建"""
        return cls(**data)


@dataclass
class RealtimeMetric:
    """实时指标"""

    name: str
    value: float
    metric_type: MetricType
    unit: Optional[str] = None
    timestamp: Optional[float] = None
    tags: Optional[Dict[str, str]] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["metric_type"] = self.metric_type.value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RealtimeMetric":
        """从字典创建"""
        data = data.copy()
        data["metric_type"] = MetricType(data["metric_type"])
        return cls(**data)


@dataclass
class TrendData:
    """趋势数据"""

    metric_name: str
    time_range: str  # e.g., "1h", "24h", "7d", "30d"
    data_points: List[TimeSeriesPoint]
    trend_direction: str  # "up", "down", "stable"
    change_percentage: float
    average_value: float
    min_value: float
    max_value: float
    timestamp: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["data_points"] = [point.to_dict() for point in self.data_points]
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrendData":
        """从字典创建"""
        data = data.copy()
        data["data_points"] = [TimeSeriesPoint.from_dict(p) for p in data["data_points"]]
        return cls(**data)


@dataclass
class DistributionData:
    """分布数据"""

    metric_name: str
    buckets: List[Dict[str, Any]]  # [{"label": "0-100", "count": 10}, ...]
    total_count: int
    mean: float
    median: float
    std_dev: float
    percentiles: Dict[int, float]  # {50: 0.5, 90: 0.9, 95: 0.95, 99: 0.99}
    timestamp: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DistributionData":
        """从字典创建"""
        return cls(**data)


@dataclass
class AnalyticsModels:
    """分析模型集合"""

    agent_metrics: List[AgentMetrics]
    user_metrics: List[UserMetrics]
    task_metrics: List[TaskMetrics]
    dashboard_stats: Optional[DashboardStats] = None
    realtime_metrics: List[RealtimeMetric] = None
    trend_data: List[TrendData] = None
    distribution_data: List[DistributionData] = None

    def __post_init__(self):
        if self.realtime_metrics is None:
            self.realtime_metrics = []
        if self.trend_data is None:
            self.trend_data = []
        if self.distribution_data is None:
            self.distribution_data = []

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "agent_metrics": [m.to_dict() for m in self.agent_metrics],
            "user_metrics": [m.to_dict() for m in self.user_metrics],
            "task_metrics": [m.to_dict() for m in self.task_metrics],
            "dashboard_stats": self.dashboard_stats.to_dict() if self.dashboard_stats else None,
            "realtime_metrics": [m.to_dict() for m in self.realtime_metrics],
            "trend_data": [t.to_dict() for t in self.trend_data],
            "distribution_data": [d.to_dict() for d in self.distribution_data],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnalyticsModels":
        """从字典创建"""
        return cls(
            agent_metrics=[AgentMetrics.from_dict(m) for m in data.get("agent_metrics", [])],
            user_metrics=[UserMetrics.from_dict(m) for m in data.get("user_metrics", [])],
            task_metrics=[TaskMetrics.from_dict(m) for m in data.get("task_metrics", [])],
            dashboard_stats=DashboardStats.from_dict(data["dashboard_stats"]) if data.get("dashboard_stats") else None,
            realtime_metrics=[RealtimeMetric.from_dict(m) for m in data.get("realtime_metrics", [])],
            trend_data=[TrendData.from_dict(t) for t in data.get("trend_data", [])],
            distribution_data=[DistributionData.from_dict(d) for d in data.get("distribution_data", [])],
        )
