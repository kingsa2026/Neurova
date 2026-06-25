"""
MetaCognitionModule — 元认知模块

监控和管理认知过程
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class CognitiveProcess(str, Enum):
    """认知过程类型"""

    RETRIEVAL = "retrieval"
    ENCODING = "encoding"
    CONSOLIDATION = "consolidation"
    REASONING = "reasoning"
    DECISION = "decision"


@dataclass
class CognitiveEvent:
    """认知事件"""

    event_id: str
    process_type: CognitiveProcess
    description: str
    duration_ms: float
    success: bool
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "process_type": self.process_type.value,
            "description": self.description,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


class MetaCognitionModule:
    """
    元认知模块

    监控和管理认知过程，支持：
    - 认知事件记录
    - 性能监控
    - 认知策略调整
    """

    def __init__(self, max_history: int = 1000):
        """
        Args:
            max_history: 最大历史记录数
        """
        self._max_history = max_history
        self._lock = threading.RLock()
        self._initialized = False

        # 认知事件历史
        self._events: List[CognitiveEvent] = []

        # 认知统计
        self._process_stats: Dict[str, Dict[str, Any]] = {}

        # 当前认知状态
        self._current_process: Optional[CognitiveProcess] = None
        self._process_start_time: Optional[float] = None

    @property
    def name(self) -> str:
        """模块名称"""
        return "meta_cognition_module"

    def init(self) -> bool:
        """初始化模块"""
        self._initialized = True
        logger.info("MetaCognitionModule initialized")
        return True

    def shutdown(self) -> None:
        """关闭模块"""
        self._initialized = False
        logger.info("MetaCognitionModule shutdown")

    def start_process(self, process_type: CognitiveProcess) -> str:
        """
        开始认知过程

        Args:
            process_type: 过程类型

        Returns:
            事件ID
        """
        event_id = f"{process_type.value}_{int(time.time() * 1000)}"

        with self._lock:
            self._current_process = process_type
            self._process_start_time = time.time()

        return event_id

    def end_process(
        self,
        event_id: str,
        description: str,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CognitiveEvent:
        """
        结束认知过程

        Args:
            event_id: 事件ID
            description: 描述
            success: 是否成功
            metadata: 额外元数据

        Returns:
            认知事件记录
        """
        with self._lock:
            duration_ms = 0.0
            if self._process_start_time:
                duration_ms = (time.time() - self._process_start_time) * 1000

            process_type = self._current_process or CognitiveProcess.REASONING

            event = CognitiveEvent(
                event_id=event_id,
                process_type=process_type,
                description=description,
                duration_ms=duration_ms,
                success=success,
                metadata=metadata or {},
            )

            # 添加到历史
            self._events.append(event)
            if len(self._events) > self._max_history:
                self._events = self._events[-self._max_history :]

            # 更新统计
            self._update_stats(event)

            # 重置当前状态
            self._current_process = None
            self._process_start_time = None

            return event

    def record_event(
        self,
        process_type: CognitiveProcess,
        description: str,
        duration_ms: float = 0.0,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CognitiveEvent:
        """记录认知事件"""
        event_id = f"{process_type.value}_{int(time.time() * 1000)}"

        event = CognitiveEvent(
            event_id=event_id,
            process_type=process_type,
            description=description,
            duration_ms=duration_ms,
            success=success,
            metadata=metadata or {},
        )

        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max_history:
                self._events = self._events[-self._max_history :]

            self._update_stats(event)

        return event

    def get_recent_events(self, count: int = 10) -> List[CognitiveEvent]:
        """获取最近的事件"""
        with self._lock:
            return self._events[-count:]

    def get_events_by_type(
        self,
        process_type: CognitiveProcess,
        limit: int = 10,
    ) -> List[CognitiveEvent]:
        """按类型获取事件"""
        with self._lock:
            events = [e for e in self._events if e.process_type == process_type]
            return events[-limit:]

    def get_process_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取认知过程统计"""
        with self._lock:
            return dict(self._process_stats)

    def get_success_rate(self, process_type: Optional[CognitiveProcess] = None) -> float:
        """获取成功率"""
        with self._lock:
            if process_type:
                events = [e for e in self._events if e.process_type == process_type]
            else:
                events = self._events

            if not events:
                return 1.0

            success_count = sum(1 for e in events if e.success)
            return success_count / len(events)

    def get_average_duration(self, process_type: CognitiveProcess) -> float:
        """获取平均持续时间"""
        with self._lock:
            events = [e for e in self._events if e.process_type == process_type]

            if not events:
                return 0.0

            total_duration = sum(e.duration_ms for e in events)
            return total_duration / len(events)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                "total_events": len(self._events),
                "process_stats": dict(self._process_stats),
                "current_process": self._current_process.value if self._current_process else None,
                "success_rate": self.get_success_rate(),
            }

    def _update_stats(self, event: CognitiveEvent) -> None:
        """更新统计信息"""
        process_name = event.process_type.value

        if process_name not in self._process_stats:
            self._process_stats[process_name] = {
                "count": 0,
                "success_count": 0,
                "total_duration_ms": 0.0,
            }

        stats = self._process_stats[process_name]
        stats["count"] += 1
        if event.success:
            stats["success_count"] += 1
        stats["total_duration_ms"] += event.duration_ms
