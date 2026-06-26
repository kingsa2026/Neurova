from __future__ import annotations

"""
Neurova 数据分析模块 - 数据收集器
负责收集和聚合系统指标数据
"""

import asyncio
import threading
from neurova.core.logger import get_logger
import time
import typing
from collections import defaultdict
from typing import Any, Dict, List, Optional

# api imports
from neurova.agent_core import Agent

# analytics imports
from neurova.analytics.models import (
    AgentMetrics,
    AgentStatus,
    DashboardStats,
    DistributionData,
    MetricType,
    RealtimeMetric,
    TaskMetrics,
    TaskStatus,
    TimeSeriesPoint,
    TrendData,
    UserMetrics,
)
from neurova.auth.user_model import User

logger = get_logger(__name__)


class MetricsCollector:
    """
    数据指标收集器
    负责收集、聚合和存储系统指标数据
    """

    def __init__(self, max_history: int = 1000):
        """
        初始化指标收集器

        Args:
            max_history: 最大历史记录数
        """
        self.max_history = max_history
        self._lock = asyncio.Lock()

        # 存储指标数据
        self._agent_metrics: Dict[str, AgentMetrics] = {}
        self._user_metrics: Dict[str, UserMetrics] = {}
        self._task_metrics: Dict[str, TaskMetrics] = {}
        self._realtime_metrics: List[RealtimeMetric] = []
        self._time_series: Dict[str, List[TimeSeriesPoint]] = defaultdict(list)

        # 仪表盘统计缓存
        self._dashboard_stats: Optional[DashboardStats] = None
        self._last_dashboard_update: float = 0

        # 趋势数据缓存
        self._trend_cache: Dict[str, TrendData] = {}
        self._last_trend_update: float = 0

        # 分布数据缓存
        self._distribution_cache: Dict[str, DistributionData] = {}
        self._last_distribution_update: float = 0

        logger.info("MetricsCollector initialized with max_history=%d", max_history)

    async def collect_agent_metrics(self, agent: Agent) -> AgentMetrics:
        """
        收集Agent指标

        Args:
            agent: Agent实例

        Returns:
            Agent指标数据
        """
        async with self._lock:
            try:
                # 获取Agent状态信息
                agent_id = agent.agent_id if hasattr(agent, "agent_id") else str(id(agent))
                agent_name = agent.name if hasattr(agent, "name") else f"Agent-{agent_id[:8]}"

                # 模拟指标收集（实际项目中应从真实监控获取）
                metrics = self._generate_mock_agent_metrics(agent_id, agent_name)

                # 存储指标
                self._agent_metrics[agent_id] = metrics

                # 记录时间序列
                self._add_time_series_point(f"agent.{agent_id}.requests", metrics.total_requests)
                self._add_time_series_point(f"agent.{agent_id}.response_time", metrics.average_response_time)
                self._add_time_series_point(f"agent.{agent_id}.memory", metrics.memory_usage_mb)

                return metrics

            except Exception as e:
                logger.error("Failed to collect agent metrics: %s", e)
                raise

    def _generate_mock_agent_metrics(self, agent_id: str, agent_name: str) -> AgentMetrics:
        """
        生成模拟Agent指标

        Args:
            agent_id: Agent ID
            agent_name: Agent名称

        Returns:
            模拟的Agent指标
        """
        import random

        # 模拟各种状态
        status_choices = list(AgentStatus)
        status = random.choice(status_choices)

        # 生成模拟数据
        total_requests = random.randint(100, 10000)
        success_rate = random.uniform(0.8, 0.99)
        successful_requests = int(total_requests * success_rate)
        failed_requests = total_requests - successful_requests

        return AgentMetrics(
            agent_id=agent_id,
            agent_name=agent_name,
            status=status,
            uptime_seconds=random.uniform(3600, 86400),  # 1-24小时
            total_requests=total_requests,
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            average_response_time=random.uniform(0.1, 2.0),  # 100ms-2s
            memory_usage_mb=random.uniform(100, 1000),  # 100MB-1GB
            cpu_usage_percent=random.uniform(5, 80),  # 5%-80%
            active_tasks=random.randint(0, 10),
            queued_tasks=random.randint(0, 5),
            last_active_at=time.time() - random.uniform(0, 300),  # 最近5分钟
            metadata={"version": "1.0.0", "capabilities": ["chat", "tool_use", "memory"], "model": "gpt-4"},
        )

    async def get_all_agent_metrics(self) -> List[AgentMetrics]:
        """
        获取所有Agent指标

        Returns:
            Agent指标列表
        """
        async with self._lock:
            return list(self._agent_metrics.values())

    async def update_agent_metrics(self, agent_id: str, **kwargs) -> Optional[AgentMetrics]:
        """
        更新Agent指标

        Args:
            agent_id: Agent ID
            **kwargs: 要更新的指标字段

        Returns:
            更新后的Agent指标，如果不存在则返回None
        """
        async with self._lock:
            if agent_id not in self._agent_metrics:
                logger.warning("Agent metrics not found for agent_id: %s", agent_id)
                return None

            metrics = self._agent_metrics[agent_id]

            # 更新字段
            for key, value in kwargs.items():
                if hasattr(metrics, key):
                    setattr(metrics, key, value)

            # 更新时间戳
            metrics.last_active_at = time.time()

            logger.info("Updated agent metrics for %s: %s", agent_id, kwargs.keys())
            return metrics

    async def collect_user_metrics(self, user: User) -> UserMetrics:
        """
        收集用户指标

        Args:
            user: 用户实例

        Returns:
            用户指标数据
        """
        async with self._lock:
            try:
                user_id = user.user_id if hasattr(user, "user_id") else str(id(user))
                username = user.username if hasattr(user, "username") else f"User-{user_id[:8]}"

                # 模拟指标收集
                metrics = self._generate_mock_user_metrics(user_id, username)

                # 存储指标
                self._user_metrics[user_id] = metrics

                # 记录时间序列
                self._add_time_series_point(f"user.{user_id}.sessions", metrics.total_sessions)
                self._add_time_series_point(f"user.{user_id}.messages", metrics.total_messages)
                self._add_time_series_point(f"user.{user_id}.tokens", metrics.total_tokens_used)

                return metrics

            except Exception as e:
                logger.error("Failed to collect user metrics: %s", e)
                raise

    def _generate_mock_user_metrics(self, user_id: str, username: str) -> UserMetrics:
        """
        生成模拟用户指标

        Args:
            user_id: 用户ID
            username: 用户名

        Returns:
            模拟的用户指标
        """
        import random

        total_sessions = random.randint(10, 100)
        messages_per_session = random.uniform(5, 20)
        total_messages = int(total_sessions * messages_per_session)

        return UserMetrics(
            user_id=user_id,
            username=username,
            total_sessions=total_sessions,
            total_messages=total_messages,
            average_session_duration=random.uniform(300, 3600),  # 5分钟-1小时
            total_tokens_used=random.randint(10000, 1000000),
            total_cost=random.uniform(1.0, 100.0),  # $1-$100
            favorite_agent_id=f"agent-{random.randint(1, 5)}",
            last_active_at=time.time() - random.uniform(0, 86400),  # 最近24小时
            metadata={
                "subscription": random.choice(["free", "pro", "enterprise"]),
                "preferred_model": random.choice(["gpt-4", "gpt-3.5-turbo", "claude-3"]),
                "language": random.choice(["en", "zh", "ja"]),
            },
        )

    async def get_all_user_metrics(self) -> List[UserMetrics]:
        """
        获取所有用户指标

        Returns:
            用户指标列表
        """
        async with self._lock:
            return list(self._user_metrics.values())

    async def collect_task_metrics(
        self, task_id: str, task_type: str, agent_id: str, user_id: Optional[str] = None
    ) -> TaskMetrics:
        """
        收集任务指标

        Args:
            task_id: 任务ID
            task_type: 任务类型
            agent_id: Agent ID
            user_id: 用户ID（可选）

        Returns:
            任务指标数据
        """
        async with self._lock:
            try:
                metrics = TaskMetrics(
                    task_id=task_id,
                    task_type=task_type,
                    status=TaskStatus.PENDING,
                    agent_id=agent_id,
                    user_id=user_id,
                    start_time=time.time(),
                    metadata={"created_by": "collector", "priority": "normal"},
                )

                # 存储指标
                self._task_metrics[task_id] = metrics

                logger.info("Collected task metrics for task %s", task_id)
                return metrics

            except Exception as e:
                logger.error("Failed to collect task metrics: %s", e)
                raise

    async def record_task(
        self, task_id: str, task_type: str, agent_id: str, user_id: Optional[str] = None
    ) -> TaskMetrics:
        """
        记录任务（别名方法）

        Args:
            task_id: 任务ID
            task_type: 任务类型
            agent_id: Agent ID
            user_id: 用户ID（可选）

        Returns:
            任务指标数据
        """
        return await self.collect_task_metrics(task_id, task_type, agent_id, user_id)

    async def update_task_status(
        self, task_id: str, status: TaskStatus, error_message: Optional[str] = None
    ) -> Optional[TaskMetrics]:
        """
        更新任务状态

        Args:
            task_id: 任务ID
            status: 新状态
            error_message: 错误消息（如果失败）

        Returns:
            更新后的任务指标，如果不存在则返回None
        """
        async with self._lock:
            if task_id not in self._task_metrics:
                logger.warning("Task metrics not found for task_id: %s", task_id)
                return None

            metrics = self._task_metrics[task_id]

            if status == TaskStatus.COMPLETED:
                metrics.complete()
            elif status == TaskStatus.FAILED:
                metrics.fail(error_message or "Unknown error")
            else:
                metrics.status = status

            # 记录时间序列
            self._add_time_series_point(f"task.{task_id}.status_change", 1)

            logger.info("Updated task %s status to %s", task_id, status.value)
            return metrics

    async def record_realtime_metric(
        self,
        name: str,
        value: float,
        metric_type: MetricType,
        unit: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> RealtimeMetric:
        """
        记录实时指标

        Args:
            name: 指标名称
            value: 指标值
            metric_type: 指标类型
            unit: 单位
            tags: 标签

        Returns:
            实时指标数据
        """
        async with self._lock:
            metric = RealtimeMetric(
                name=name, value=value, metric_type=metric_type, unit=unit, tags=tags, metadata={"source": "collector"}
            )

            # 存储指标
            self._realtime_metrics.append(metric)

            # 限制历史记录数
            if len(self._realtime_metrics) > self.max_history:
                self._realtime_metrics = self._realtime_metrics[-self.max_history :]

            # 记录时间序列
            self._add_time_series_point(f"realtime.{name}", value)

            return metric

    async def get_realtime_metrics(self, name: Optional[str] = None, limit: int = 100) -> List[RealtimeMetric]:
        """
        获取实时指标

        Args:
            name: 指标名称过滤
            limit: 返回数量限制

        Returns:
            实时指标列表
        """
        async with self._lock:
            metrics = self._realtime_metrics

            if name:
                metrics = [m for m in metrics if m.name == name]

            return metrics[-limit:] if limit else metrics

    def _add_time_series_point(self, key: str, value: float, metadata: Optional[Dict[str, Any]] = None):
        """
        添加时间序列点

        Args:
            key: 序列键
            value: 值
            metadata: 元数据
        """
        point = TimeSeriesPoint(timestamp=time.time(), value=value, metadata=metadata)

        series = self._time_series[key]
        series.append(point)

        # 限制历史记录数
        if len(series) > self.max_history:
            self._time_series[key] = series[-self.max_history :]

    async def get_time_series(
        self, key: str, start_time: Optional[float] = None, end_time: Optional[float] = None
    ) -> List[TimeSeriesPoint]:
        """
        获取时间序列数据

        Args:
            key: 序列键
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            时间序列点列表
        """
        async with self._lock:
            series = self._time_series.get(key, [])

            if start_time or end_time:
                filtered = []
                for point in series:
                    if start_time and point.timestamp < start_time:
                        continue
                    if end_time and point.timestamp > end_time:
                        continue
                    filtered.append(point)
                return filtered

            return series.copy()

    async def get_dashboard_stats(self) -> DashboardStats:
        """
        获取仪表盘统计

        Returns:
            仪表盘统计数据
        """
        async with self._lock:
            current_time = time.time()

            # 每5分钟更新一次缓存
            if self._dashboard_stats and current_time - self._last_dashboard_update < 300:
                return self._dashboard_stats

            # 计算统计数据
            agent_metrics = list(self._agent_metrics.values())
            user_metrics = list(self._user_metrics.values())

            total_agents = len(agent_metrics)
            active_agents = sum(1 for m in agent_metrics if m.status == AgentStatus.ACTIVE)

            total_users = len(user_metrics)
            active_users = sum(1 for m in user_metrics if m.last_active_at and current_time - m.last_active_at < 3600)

            total_requests = sum(m.total_requests for m in agent_metrics)
            successful_requests = sum(m.successful_requests for m in agent_metrics)
            failed_requests = sum(m.failed_requests for m in agent_metrics)

            # 计算请求速率（最近1小时）
            recent_requests = 0
            for series in self._time_series.values():
                for point in series[-3600:]:  # 最近3600个点
                    if current_time - point.timestamp < 3600:
                        recent_requests += 1

            requests_per_minute = recent_requests / 60 if recent_requests > 0 else 0

            # 计算平均响应时间
            response_times = [m.average_response_time for m in agent_metrics if m.average_response_time > 0]
            average_response_time = sum(response_times) / len(response_times) if response_times else 0

            # 计算错误率
            error_rate = failed_requests / total_requests if total_requests > 0 else 0

            # 计算总token使用和成本
            total_tokens_used = sum(m.total_tokens_used for m in user_metrics)
            total_cost = sum(m.total_cost for m in user_metrics)

            # 计算运行时间
            uptime_seconds = current_time - min(m.created_at for m in agent_metrics) if agent_metrics else 0

            self._dashboard_stats = DashboardStats(
                total_agents=total_agents,
                active_agents=active_agents,
                total_users=total_users,
                active_users=active_users,
                total_requests=total_requests,
                requests_per_minute=requests_per_minute,
                average_response_time=average_response_time,
                error_rate=error_rate,
                total_tokens_used=total_tokens_used,
                total_cost=total_cost,
                uptime_seconds=uptime_seconds,
                timestamp=current_time,
                metadata={
                    "successful_requests": successful_requests,
                    "failed_requests": failed_requests,
                    "recent_requests": recent_requests,
                },
            )

            self._last_dashboard_update = current_time
            return self._dashboard_stats

    async def get_trend_data(self, metric_name: str, time_range: str = "24h") -> TrendData:
        """
        获取趋势数据

        Args:
            metric_name: 指标名称
            time_range: 时间范围（1h, 24h, 7d, 30d）

        Returns:
            趋势数据
        """
        async with self._lock:
            cache_key = f"{metric_name}_{time_range}"
            current_time = time.time()

            # 每5分钟更新一次缓存
            if cache_key in self._trend_cache and current_time - self._last_trend_update < 300:
                return self._trend_cache[cache_key]

            # 解析时间范围
            time_ranges = {"1h": 3600, "24h": 86400, "7d": 604800, "30d": 2592000}
            duration = time_ranges.get(time_range, 86400)
            start_time = current_time - duration

            # 获取时间序列数据
            series = self._time_series.get(metric_name, [])
            filtered_points = [p for p in series if p.timestamp >= start_time]

            if not filtered_points:
                # 返回空趋势数据
                trend = TrendData(
                    metric_name=metric_name,
                    time_range=time_range,
                    data_points=[],
                    trend_direction="stable",
                    change_percentage=0.0,
                    average_value=0.0,
                    min_value=0.0,
                    max_value=0.0,
                    timestamp=current_time,
                )
            else:
                # 计算趋势
                values = [p.value for p in filtered_points]
                average_value = sum(values) / len(values)
                min_value = min(values)
                max_value = max(values)

                # 计算变化百分比
                if len(values) >= 2:
                    first_value = values[0]
                    last_value = values[-1]
                    if first_value != 0:
                        change_percentage = ((last_value - first_value) / first_value) * 100
                    else:
                        change_percentage = 0.0

                    # 确定趋势方向
                    if change_percentage > 5:
                        trend_direction = "up"
                    elif change_percentage < -5:
                        trend_direction = "down"
                    else:
                        trend_direction = "stable"
                else:
                    change_percentage = 0.0
                    trend_direction = "stable"

                trend = TrendData(
                    metric_name=metric_name,
                    time_range=time_range,
                    data_points=filtered_points[-100:],  # 限制返回点数
                    trend_direction=trend_direction,
                    change_percentage=change_percentage,
                    average_value=average_value,
                    min_value=min_value,
                    max_value=max_value,
                    timestamp=current_time,
                )

            self._trend_cache[cache_key] = trend
            self._last_trend_update = current_time
            return trend

    async def get_distribution_data(self, metric_name: str) -> DistributionData:
        """
        获取分布数据

        Args:
            metric_name: 指标名称

        Returns:
            分布数据
        """
        async with self._lock:
            current_time = time.time()

            # 每5分钟更新一次缓存
            if metric_name in self._distribution_cache and current_time - self._last_distribution_update < 300:
                return self._distribution_cache[metric_name]

            # 获取时间序列数据
            series = self._time_series.get(metric_name, [])
            values = [p.value for p in series]

            if not values:
                # 返回空分布数据
                distribution = DistributionData(
                    metric_name=metric_name,
                    buckets=[],
                    total_count=0,
                    mean=0.0,
                    median=0.0,
                    std_dev=0.0,
                    percentiles={50: 0.0, 90: 0.0, 95: 0.0, 99: 0.0},
                    timestamp=current_time,
                )
            else:
                # 计算统计值
                total_count = len(values)
                mean = sum(values) / total_count

                # 计算中位数
                sorted_values = sorted(values)
                if total_count % 2 == 0:
                    median = (sorted_values[total_count // 2 - 1] + sorted_values[total_count // 2]) / 2
                else:
                    median = sorted_values[total_count // 2]

                # 计算标准差
                variance = sum((x - mean) ** 2 for x in values) / total_count
                std_dev = variance**0.5

                # 计算百分位数
                def percentile(data, percent):
                    k = (len(data) - 1) * percent / 100
                    f = int(k)
                    c = int(k) + 1
                    if c >= len(data):
                        return data[-1]
                    return data[f] + (k - f) * (data[c] - data[f])

                percentiles = {
                    50: percentile(sorted_values, 50),
                    90: percentile(sorted_values, 90),
                    95: percentile(sorted_values, 95),
                    99: percentile(sorted_values, 99),
                }

                # 创建分布桶
                min_val = min(values)
                max_val = max(values)
                bucket_count = min(10, total_count)  # 最多10个桶
                bucket_size = (max_val - min_val) / bucket_count if max_val > min_val else 1

                buckets = []
                for i in range(bucket_count):
                    bucket_min = min_val + i * bucket_size
                    bucket_max = min_val + (i + 1) * bucket_size
                    bucket_values = [v for v in values if bucket_min <= v < bucket_max]

                    buckets.append(
                        {
                            "label": f"{bucket_min:.1f}-{bucket_max:.1f}",
                            "count": len(bucket_values),
                            "min": bucket_min,
                            "max": bucket_max,
                        }
                    )

                distribution = DistributionData(
                    metric_name=metric_name,
                    buckets=buckets,
                    total_count=total_count,
                    mean=mean,
                    median=median,
                    std_dev=std_dev,
                    percentiles=percentiles,
                    timestamp=current_time,
                )

            self._distribution_cache[metric_name] = distribution
            self._last_distribution_update = current_time
            return distribution

    async def generate_realtime_updates(self, interval: float = 1.0) -> typing.AsyncGenerator[Dict[str, Any], None]:
        """
        生成实时更新流

        Args:
            interval: 更新间隔（秒）

        Yields:
            实时更新数据
        """
        while True:
            try:
                # 收集当前状态
                dashboard = await self.get_dashboard_stats()
                realtime_metrics = await self.get_realtime_metrics(limit=10)

                update = {
                    "timestamp": time.time(),
                    "dashboard": dashboard.to_dict(),
                    "realtime_metrics": [m.to_dict() for m in realtime_metrics],
                    "active_agents": len([m for m in self._agent_metrics.values() if m.status == AgentStatus.ACTIVE]),
                    "active_users": len(
                        [
                            m
                            for m in self._user_metrics.values()
                            if m.last_active_at and time.time() - m.last_active_at < 3600
                        ]
                    ),
                }

                yield update

                await asyncio.sleep(interval)

            except Exception as e:
                logger.error("Error generating realtime updates: %s", e)
                await asyncio.sleep(interval)

    async def record_agent_request(
        self,
        agent_id: str,
        request_type: str,
        success: bool,
        response_time: float,
        tokens_used: int = 0,
        cost: float = 0.0,
    ):
        """
        记录Agent请求

        Args:
            agent_id: Agent ID
            request_type: 请求类型
            success: 是否成功
            response_time: 响应时间
            tokens_used: 使用的token数
            cost: 成本
        """
        async with self._lock:
            if agent_id in self._agent_metrics:
                metrics = self._agent_metrics[agent_id]
                metrics.total_requests += 1
                if success:
                    metrics.successful_requests += 1
                else:
                    metrics.failed_requests += 1

                # 更新平均响应时间
                total_time = metrics.average_response_time * (metrics.total_requests - 1) + response_time
                metrics.average_response_time = total_time / metrics.total_requests

                metrics.last_active_at = time.time()

            # 记录实时指标
            await self.record_realtime_metric(
                name=f"agent.{agent_id}.request",
                value=response_time,
                metric_type=MetricType.HISTOGRAM,
                unit="seconds",
                tags={"agent_id": agent_id, "request_type": request_type, "success": str(success)},
            )

            # 记录时间序列
            self._add_time_series_point(f"agent.{agent_id}.request_time", response_time)
            if tokens_used > 0:
                self._add_time_series_point(f"agent.{agent_id}.tokens", tokens_used)
            if cost > 0:
                self._add_time_series_point(f"agent.{agent_id}.cost", cost)


# 单例并发保护：双重检查锁模式
# 修复 P0-2 (C2)：原 hasattr(get_collector, "_instance") 写法无锁，TOCTOU
# 模板：neurova/cognitive/orchestrator.py:358-369
_collector_singleton: Optional[MetricsCollector] = None
_collector_lock = threading.Lock()


def get_collector() -> MetricsCollector:
    """
    获取收集器实例（单例模式，并发安全）

    Returns:
        MetricsCollector实例
    """
    global _collector_singleton
    with _collector_lock:
        if _collector_singleton is None:
            _collector_singleton = MetricsCollector()
        return _collector_singleton


def reset_collector():
    """
    重置收集器实例（用于测试）
    """
    global _collector_singleton
    with _collector_lock:
        _collector_singleton = None
