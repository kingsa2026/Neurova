"""Supervisor-Worker 多 Agent 编排（进程内 ACP 默认，MQTT 可选）。"""
from .contracts import SupervisorTask, WorkerResult
from .bus import (
    InProcessWorkerBus, MqttWorkerBus, SupervisorBusError, buildWorkerBus,
)
from .ledger import SupervisorTaskLedger, get_supervisor_ledger
from .orchestrator import SupervisorOrchestrator

__all__ = [
    "SupervisorTask",
    "WorkerResult",
    "InProcessWorkerBus",
    "MqttWorkerBus",
    "SupervisorBusError",
    "buildWorkerBus",
    "SupervisorTaskLedger",
    "get_supervisor_ledger",
    "SupervisorOrchestrator",
]
