"""
轨迹模型

定义 Agent 执行过程中用于追踪的数据结构。
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class TrajectoryEventType(Enum):
    """轨迹事件类型"""

    SESSION_START = "session_start"
    SESSION_END = "session_end"
    USER_INPUT = "user_input"
    ROUTE_START = "route_start"
    ROUTE_END = "route_end"
    ROUTE_RESULT = "route_result"
    MEMORY_RETRIEVAL_START = "memory_retrieval_start"
    MEMORY_RETRIEVAL_END = "memory_retrieval_end"
    MEMORY_RETRIEVAL_RESULT = "memory_retrieval_result"
    MEMORY_STORAGE_START = "memory_storage_start"
    MEMORY_STORAGE_END = "memory_storage_end"
    CONTEXT_BUILD_START = "context_build_start"
    CONTEXT_BUILD_END = "context_build_end"
    CONTEXT_COMPRESS = "context_compress"
    LLM_CALL_START = "llm_call_start"
    LLM_CALL_END = "llm_call_end"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    TOOL_CALL_ERROR = "tool_call_error"
    OUTPUT_END = "output_end"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    DEBUG = "debug"


@dataclass
class TrajectoryEvent:
    """轨迹事件

    记录 Agent 执行过程中的一个事件。
    """

    event_type: TrajectoryEventType
    timestamp: str = ""
    session_id: str = ""
    agent_id: str = ""
    user_id: str = ""
    trace_id: str = ""
    span_id: str = ""
    parent_span_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    status: str = "success"
    error_message: Optional[str] = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.span_id:
            self.span_id = str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "data": self.data,
            "duration_ms": self.duration_ms,
            "cpu_usage": self.cpu_usage,
            "memory_usage": self.memory_usage,
            "status": self.status,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrajectoryEvent":
        return cls(
            event_type=TrajectoryEventType(data.get("event_type", "info")),
            **{k: v for k, v in data.items() if k != "event_type"}
        )


@dataclass
class TrajectorySpan:
    """轨迹 Span

    表示一个有开始和结束的事件范围（类似 OpenTelemetry Span）。
    用于追踪一个完整操作（如 LLM 调用、工具调用）。
    """

    span_id: str = ""
    trace_id: str = ""
    parent_span_id: Optional[str] = None
    session_id: str = ""
    agent_id: str = ""
    user_id: str = ""
    operation_name: str = ""
    operation_type: str = ""
    start_time: str = ""
    end_time: Optional[str] = None
    duration_ms: float = 0.0
    status: str = "running"
    error_message: Optional[str] = None
    events: List[TrajectoryEvent] = field(default_factory=list)
    child_spans: List["TrajectorySpan"] = field(default_factory=list)

    def __post_init__(self):
        if not self.span_id:
            self.span_id = str(uuid.uuid4())
        if not self.start_time:
            self.start_time = datetime.now(timezone.utc).isoformat()

    def end(self, status: str = "success", error_message: Optional[str] = None) -> None:
        self.end_time = datetime.now(timezone.utc).isoformat()
        if self.start_time and self.end_time:
            start = datetime.fromisoformat(self.start_time.replace("Z", "+00:00"))
            end = datetime.fromisoformat(self.end_time.replace("Z", "+00:00"))
            self.duration_ms = (end - start).total_seconds() * 1000
        self.status = status
        self.error_message = error_message

    def add_event(self, event: TrajectoryEvent) -> None:
        event.trace_id = self.trace_id
        event.span_id = self.span_id
        self.events.append(event)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "operation_name": self.operation_name,
            "operation_type": self.operation_type,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error_message": self.error_message,
            "events": [e.to_dict() for e in self.events],
            "child_spans": [s.to_dict() for s in self.child_spans],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrajectorySpan":
        events = [TrajectoryEvent.from_dict(e) for e in data.get("events", [])]
        child_spans = [TrajectorySpan.from_dict(s) for s in data.get("child_spans", [])]
        return cls(
            events=events,
            child_spans=child_spans,
            **{k: v for k, v in data.items() if k not in ("events", "child_spans")}
        )


@dataclass
class Trajectory:
    """完整轨迹

    包含一个 Session 或 Request 的完整执行轨迹。
    """

    trace_id: str = ""
    session_id: str = ""
    agent_id: str = ""
    user_id: str = ""
    start_time: str = ""
    end_time: Optional[str] = None
    total_duration_ms: float = 0.0
    root_span: Optional[TrajectorySpan] = None
    spans: Dict[str, TrajectorySpan] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    stats: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.trace_id:
            self.trace_id = str(uuid.uuid4())
        if not self.start_time:
            self.start_time = datetime.now(timezone.utc).isoformat()

    def add_span(self, span: TrajectorySpan) -> None:
        span.trace_id = self.trace_id
        self.spans[span.span_id] = span
        if span.parent_span_id and span.parent_span_id in self.spans:
            self.spans[span.parent_span_id].child_spans.append(span)

    def get_span(self, span_id: str) -> Optional[TrajectorySpan]:
        return self.spans.get(span_id)

    def get_child_spans(self, parent_span_id: str) -> List[TrajectorySpan]:
        if parent_span_id in self.spans:
            return self.spans[parent_span_id].child_spans
        return []

    def end(self) -> None:
        self.end_time = datetime.now(timezone.utc).isoformat()
        if self.start_time and self.end_time:
            start = datetime.fromisoformat(self.start_time.replace("Z", "+00:00"))
            end = datetime.fromisoformat(self.end_time.replace("Z", "+00:00"))
            self.total_duration_ms = (end - start).total_seconds() * 1000

    def _compute_stats(self) -> None:
        self.stats["span_count"] = len(self.spans)
        self.stats["total_duration_ms"] = self.total_duration_ms

        # 按操作类型统计
        tags = {}
        for span in self.spans.values():
            op_type = span.operation_name.lower() if span.operation_name else "unknown"
            tags[op_type] = tags.get(op_type, 0) + 1
        self.stats["tags"] = tags

        # 按状态统计
        status_counts = {}
        for span in self.spans.values():
            status_counts[span.status] = status_counts.get(span.status, 0) + 1
        self.stats["status"] = status_counts

        # 事件统计
        event_counts = {}
        for span in self.spans.values():
            for event in span.events:
                event_type = event.event_type.value
                event_counts[event_type] = event_counts.get(event_type, 0) + 1
        self.stats["events"] = event_counts

    def to_dict(self) -> Dict[str, Any]:
        self._compute_stats()
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            # user_id 补录（预存失败修复 2026-09-02）：原 to_dict 漏该字段——
            # 保存的轨迹 JSON 无 user_id，load/list 按用户过滤永远失配
            "user_id": self.user_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_duration_ms": self.total_duration_ms,
            "root_span": self.root_span.span_id if self.root_span else None,
            "spans": {k: v.to_dict() for k, v in self.spans.items()},
            "metadata": self.metadata,
            "stats": self.stats,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Trajectory":
        spans = {k: TrajectorySpan.from_dict(v) for k, v in data.get("spans", {}).items()}
        root_span = None
        if data.get("root_span") and data["root_span"] in spans:
            root_span = spans[data["root_span"]]
        return cls(
            spans=spans, root_span=root_span, **{k: v for k, v in data.items() if k not in ("spans", "root_span")}
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "Trajectory":
        data = json.loads(json_str)
        return cls.from_dict(data)


__all__ = [
    "TrajectoryEventType",
    "TrajectoryEvent",
    "TrajectorySpan",
    "Trajectory",
]
