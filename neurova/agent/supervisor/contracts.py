"""Supervisor-Worker 任务契约。

消息走 ACP 信封（AgentMessage）承载，跨进程时由 MQTT 传输同一份 JSON；
`task_id` 是幂等键，`trace_id` 贯穿扇出与聚合。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class SupervisorTask:
    task_id: str
    role: str = "retrieve"
    payload: Dict[str, Any] = field(default_factory=dict)
    worker_id: str = ""
    deadline: float = 30.0
    max_retries: int = 1
    trace_id: str = ""

    def toDict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "role": self.role,
            "payload": dict(self.payload),
            "worker_id": self.worker_id,
            "deadline": float(self.deadline),
            "max_retries": int(self.max_retries),
            "trace_id": self.trace_id,
        }


@dataclass
class WorkerResult:
    task_id: str
    worker_id: str = ""
    success: bool = False
    items: List[Dict[str, Any]] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    attempts: int = 0
    duration: float = 0.0
    trace_id: str = ""
    replayed: bool = False

    def toDict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "success": self.success,
            "items": list(self.items),
            "data": dict(self.data),
            "error": self.error,
            "attempts": self.attempts,
            "duration": round(self.duration, 6),
            "trace_id": self.trace_id,
            "replayed": self.replayed,
        }
