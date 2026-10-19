# -*- coding: utf-8 -*-
"""工作流调度模块：现役面只有 `models` 的调度那一半与 `scheduler`。

`orchestrator.py`（FlowOrchestrator/get_orchestrator）与 `models.py` 里的 `FlowPhase`/`FlowEvent`
半区自 2026-06-03 起从未接进活链路，批 109 按 §6-312 裁乙退役；现役编排面在
`neurova/collaboration/neurflow/*`。本门面因此只再导出调度链的六个名——
"把死码声明成公共面"本身就是缺陷（形态集里门面那一族：声明面与实装面分叉）。
"""

from .models import FlowContext, ScheduledTask, compute_next_run
from .scheduler import AgentScheduler, get_scheduler, register_action_handlers

__all__ = [
    # 调度数据面
    "FlowContext",
    "ScheduledTask",
    "compute_next_run",
    # 调度执行面
    "AgentScheduler",
    "get_scheduler",
    "register_action_handlers",
]
