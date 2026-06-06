"""
执行监控器

Neurova CogArch 1.0.0 的执行组件之一
负责：执行跟踪、性能监控、日志记录、告警通知
"""

from __future__ import annotations

import asyncio
import collections
from dataclasses import dataclass, field
import datetime
import enum
import json
import logging
import os
import typing
import uuid

from enum import Enum

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class MetricType(Enum):
    """指标类型"""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


@dataclass
class MetricRecord:
    """指标记录"""
    name: str
    value: float
    metric_type: MetricType = MetricType.GAUGE
    timestamp: datetime.datetime = field(default_factory=datetime.datetime.now)
    tags: typing.Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> typing.Dict[str, typing.Any]:
        return {
            "name": self.name, "value": self.value,
            "type": self.metric_type.value,
            "timestamp": self.timestamp.isoformat(),
            "tags": self.tags
        }


@dataclass
class AlertRecord:
    """告警记录"""
    alert_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    level: AlertLevel = AlertLevel.INFO
    title: str = ""
    message: str = ""
    source: str = ""
    timestamp: datetime.datetime = field(default_factory=datetime.datetime.now)
    acknowledged: bool = False
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)
    
    def to_dict(self) -> typing.Dict[str, typing.Any]:
        return {
            "alert_id": self.alert_id, "level": self.level.value,
            "title": self.title, "message": self.message,
            "source": self.source, "timestamp": self.timestamp.isoformat(),
            "acknowledged": self.acknowledged
        }


@dataclass
class ExecutionStep:
    """执行步骤"""
    step_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    status: str = "pending"
    start_time: typing.Optional[datetime.datetime] = None
    end_time: typing.Optional[datetime.datetime] = None
    duration: typing.Optional[float] = None
    input_data: typing.Any = None
    output_data: typing.Any = None
    error: typing.Optional[str] = None


@dataclass
class ToolCallRecord:
    """工具调用记录"""
    call_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str = ""
    arguments: typing.Dict[str, typing.Any] = field(default_factory=dict)
    result: typing.Any = None
    error: typing.Optional[str] = None
    start_time: typing.Optional[datetime.datetime] = None
    end_time: typing.Optional[datetime.datetime] = None
    duration: typing.Optional[float] = None
    success: bool = True


@dataclass
class ExecutionMetrics:
    """执行指标"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    average_duration: float = 0.0
    total_duration: float = 0.0
    tool_calls: typing.Dict[str, int] = field(default_factory=dict)
    error_counts: typing.Dict[str, int] = field(default_factory=dict)


@dataclass
class ExecutionTrace:
    """执行轨迹"""
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    execution_id: str = ""
    agent_id: str = ""
    task_name: str = ""
    status: str = "running"
    start_time: datetime.datetime = field(default_factory=datetime.datetime.now)
    end_time: typing.Optional[datetime.datetime] = None
    duration: typing.Optional[float] = None
    steps: typing.List[ExecutionStep] = field(default_factory=list)
    tool_calls: typing.List[ToolCallRecord] = field(default_factory=list)
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)
    errors: typing.List[str] = field(default_factory=list)
    
    def to_dict(self) -> typing.Dict[str, typing.Any]:
        return {
            "trace_id": self.trace_id, "execution_id": self.execution_id,
            "agent_id": self.agent_id, "task_name": self.task_name,
            "status": self.status,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration": self.duration,
            "steps_count": len(self.steps),
            "tool_calls_count": len(self.tool_calls),
            "errors": self.errors
        }


class ExecutionMonitor:
    """
    执行监控器
    
    管理执行跟踪、性能指标、告警通知。
    """
    
    def __init__(self, config: typing.Dict[str, typing.Any] = None):
        self._config = config or {}
        self._lock = __import__('threading').RLock()
        
        # 指标存储
        self._metrics: typing.Dict[str, typing.List[MetricRecord]] = collections.defaultdict(list)
        self._metric_handlers: typing.List[typing.Callable] = []
        
        # 告警存储
        self._alerts: typing.List[AlertRecord] = []
        self._alert_handlers: typing.List[typing.Callable] = []
        
        # 执行轨迹
        self._traces: typing.Dict[str, ExecutionTrace] = {}
        self._execution_history: collections.deque = collections.deque(maxlen=1000)
        
        # 事件总线
        self._event_bus = None
        
        logger.info("ExecutionMonitor 初始化完成")
    
    def set_event_bus(self, event_bus) -> None:
        """设置事件总线"""
        self._event_bus = event_bus
    
    def record_metric(self, name: str, value: float, metric_type: MetricType = MetricType.GAUGE,
                      tags: typing.Dict[str, str] = None) -> None:
        """记录指标"""
        record = MetricRecord(name=name, value=value, metric_type=metric_type, tags=tags or {})
        with self._lock:
            self._metrics[name].append(record)
            # 保留最近 1000 条
            if len(self._metrics[name]) > 1000:
                self._metrics[name] = self._metrics[name][-1000:]
        
        # 通知处理器
        for handler in self._metric_handlers:
            try:
                handler(record)
            except Exception:
                pass
    
    def create_alert(self, level: AlertLevel, title: str, message: str, source: str = "") -> AlertRecord:
        """创建告警"""
        alert = AlertRecord(level=level, title=title, message=message, source=source)
        with self._lock:
            self._alerts.append(alert)
            if len(self._alerts) > 1000:
                self._alerts = self._alerts[-1000:]
        
        logger.warning(f"告警: [{level.value}] {title}: {message}")
        
        for handler in self._alert_handlers:
            try:
                handler(alert)
            except Exception:
                pass
        
        return alert
    
    def start_trace(self, execution_id: str, task_name: str = "", agent_id: str = "") -> ExecutionTrace:
        """开始执行轨迹"""
        trace = ExecutionTrace(
            execution_id=execution_id,
            task_name=task_name,
            agent_id=agent_id
        )
        with self._lock:
            self._traces[execution_id] = trace
        return trace
    
    def end_trace(self, execution_id: str, status: str = "completed") -> typing.Optional[ExecutionTrace]:
        """结束执行轨迹"""
        with self._lock:
            trace = self._traces.get(execution_id)
            if trace:
                trace.status = status
                trace.end_time = datetime.datetime.now()
                trace.duration = (trace.end_time - trace.start_time).total_seconds()
                self._execution_history.append(trace)
        return trace
    
    def add_trace_log(self, execution_id: str, message: str, level: str = "info") -> None:
        """添加轨迹日志"""
        trace = self._traces.get(execution_id)
        if trace:
            trace.metadata.setdefault("logs", []).append({
                "message": message, "level": level,
                "timestamp": datetime.datetime.now().isoformat()
            })
    
    def get_metrics(self, name: str = None, limit: int = 100) -> typing.List[MetricRecord]:
        """获取指标"""
        if name:
            return self._metrics.get(name, [])[-limit:]
        all_metrics = []
        for records in self._metrics.values():
            all_metrics.extend(records)
        all_metrics.sort(key=lambda x: x.timestamp, reverse=True)
        return all_metrics[:limit]
    
    def get_alerts(self, level: AlertLevel = None, acknowledged: bool = None, 
                   limit: int = 100) -> typing.List[AlertRecord]:
        """获取告警"""
        alerts = self._alerts
        if level:
            alerts = [a for a in alerts if a.level == level]
        if acknowledged is not None:
            alerts = [a for a in alerts if a.acknowledged == acknowledged]
        return alerts[-limit:]
    
    def acknowledge_alert(self, alert_id: str) -> bool:
        """确认告警"""
        for alert in self._alerts:
            if alert.alert_id == alert_id:
                alert.acknowledged = True
                return True
        return False
    
    def get_statistics(self) -> typing.Dict[str, typing.Any]:
        """获取统计信息"""
        total_traces = len(self._execution_history)
        completed = sum(1 for t in self._execution_history if t.status == "completed")
        failed = sum(1 for t in self._execution_history if t.status == "failed")
        
        durations = [t.duration for t in self._execution_history if t.duration is not None]
        avg_duration = sum(durations) / len(durations) if durations else 0
        
        return {
            "total_traces": total_traces,
            "completed": completed,
            "failed": failed,
            "success_rate": completed / total_traces if total_traces > 0 else 0,
            "average_duration": avg_duration,
            "total_alerts": len(self._alerts),
            "unacknowledged_alerts": sum(1 for a in self._alerts if not a.acknowledged),
            "total_metrics": sum(len(v) for v in self._metrics.values())
        }
    
    def register_metric_handler(self, handler: typing.Callable) -> None:
        """注册指标处理器"""
        self._metric_handlers.append(handler)
    
    def register_alert_handler(self, handler: typing.Callable) -> None:
        """注册告警处理器"""
        self._alert_handlers.append(handler)
    
    def start_execution(self, execution_id: str, task_name: str = "", agent_id: str = "") -> ExecutionTrace:
        """开始执行（别名）"""
        return self.start_trace(execution_id, task_name, agent_id)
    
    def record_step(self, execution_id: str, step_name: str, status: str = "running",
                    input_data: typing.Any = None) -> typing.Optional[ExecutionStep]:
        """记录执行步骤"""
        trace = self._traces.get(execution_id)
        if not trace:
            return None
        
        step = ExecutionStep(
            name=step_name,
            status=status,
            start_time=datetime.datetime.now(),
            input_data=input_data
        )
        trace.steps.append(step)
        return step
    
    def record_tool_call(self, execution_id: str, tool_name: str, arguments: typing.Dict = None,
                         result: typing.Any = None, error: str = None, duration: float = None) -> None:
        """记录工具调用"""
        trace = self._traces.get(execution_id)
        if not trace:
            return
        
        record = ToolCallRecord(
            tool_name=tool_name,
            arguments=arguments or {},
            result=result,
            error=error,
            start_time=datetime.datetime.now(),
            duration=duration,
            success=error is None
        )
        trace.tool_calls.append(record)
    
    def record_error(self, execution_id: str, error: str) -> None:
        """记录错误"""
        trace = self._traces.get(execution_id)
        if trace:
            trace.errors.append(error)
    
    def complete_execution(self, execution_id: str) -> typing.Optional[ExecutionTrace]:
        """完成执行"""
        return self.end_trace(execution_id, "completed")
    
    def fail_execution(self, execution_id: str, error: str = "") -> typing.Optional[ExecutionTrace]:
        """执行失败"""
        trace = self._traces.get(execution_id)
        if trace and error:
            trace.errors.append(error)
        return self.end_trace(execution_id, "failed")
    
    def get_execution_trace(self, execution_id: str) -> typing.Optional[ExecutionTrace]:
        """获取执行轨迹"""
        return self._traces.get(execution_id)
    
    def get_execution_metrics(self, execution_id: str) -> typing.Optional[ExecutionMetrics]:
        """获取执行指标"""
        trace = self._traces.get(execution_id)
        if not trace:
            return None
        
        tool_calls = trace.tool_calls
        successful = sum(1 for t in tool_calls if t.success)
        failed = len(tool_calls) - successful
        durations = [t.duration for t in tool_calls if t.duration is not None]
        
        tool_counts: typing.Dict[str, int] = {}
        for t in tool_calls:
            tool_counts[t.tool_name] = tool_counts.get(t.tool_name, 0) + 1
        
        error_counts: typing.Dict[str, int] = {}
        for e in trace.errors:
            error_counts[e[:50]] = error_counts.get(e[:50], 0) + 1
        
        return ExecutionMetrics(
            total_calls=len(tool_calls),
            successful_calls=successful,
            failed_calls=failed,
            average_duration=sum(durations) / len(durations) if durations else 0,
            total_duration=sum(durations),
            tool_calls=tool_counts,
            error_counts=error_counts
        )
    
    def get_all_executions(self, limit: int = 100) -> typing.List[typing.Dict[str, typing.Any]]:
        """获取所有执行记录"""
        traces = list(self._execution_history)
        traces.sort(key=lambda x: x.start_time, reverse=True)
        return [t.to_dict() for t in traces[:limit]]
    
    def get_execution_statistics(self) -> typing.Dict[str, typing.Any]:
        """获取执行统计（别名）"""
        return self.get_statistics()
    
    def _save_execution_log(self, trace: ExecutionTrace) -> None:
        """保存执行日志到文件"""
        try:
            log_dir = os.path.join("logs", "executions")
            os.makedirs(log_dir, exist_ok=True)
            path = os.path.join(log_dir, f"{trace.trace_id}.json")
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(trace.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存执行日志失败: {e}")
    
    def _cleanup_old_traces(self, max_age_days: int = 30) -> int:
        """清理旧轨迹"""
        cutoff = datetime.datetime.now() - datetime.timedelta(days=max_age_days)
        with self._lock:
            old_count = len(self._execution_history)
            self._execution_history = collections.deque(
                (t for t in self._execution_history if t.start_time > cutoff),
                maxlen=1000
            )
            return old_count - len(self._execution_history)
    
    def load_execution_history(self, log_dir: str = None) -> int:
        """加载执行历史"""
        log_dir = log_dir or os.path.join("logs", "executions")
        if not os.path.exists(log_dir):
            return 0
        
        loaded = 0
        for fname in os.listdir(log_dir):
            if fname.endswith('.json'):
                try:
                    with open(os.path.join(log_dir, fname), 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    logger.debug(f"加载执行日志: {fname}")
                    loaded += 1
                except Exception:
                    pass
        return loaded
    
    def generate_statistics_report(self) -> str:
        """生成统计报告"""
        stats = self.get_statistics()
        report = [
            "# 执行监控报告",
            f"- 总执行次数: {stats['total_traces']}",
            f"- 成功: {stats['completed']}",
            f"- 失败: {stats['failed']}",
            f"- 成功率: {stats['success_rate']:.1%}",
            f"- 平均耗时: {stats['average_duration']:.2f}s",
            f"- 总告警数: {stats['total_alerts']}",
            f"- 未确认告警: {stats['unacknowledged_alerts']}",
            f"- 指标总数: {stats['total_metrics']}"
        ]
        return "\n".join(report)
    
    def _generate_visualization_data(self) -> typing.Dict[str, typing.Any]:
        """生成可视化数据"""
        traces = list(self._execution_history)
        
        # 时间分布
        hourly: typing.Dict[str, int] = {}
        for t in traces:
            hour = t.start_time.strftime("%Y-%m-%d %H:00")
            hourly[hour] = hourly.get(hour, 0) + 1
        
        # 状态分布
        status_counts: typing.Dict[str, int] = {}
        for t in traces:
            status_counts[t.status] = status_counts.get(t.status, 0) + 1
        
        return {"hourly_distribution": hourly, "status_distribution": status_counts}