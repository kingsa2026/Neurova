# -*- coding: utf-8 -*-
"""协作模块：现役面只有工作流调度（`workflow/`）。

本门面**不再把死岛声明成公共面**（§6-312 的 D19）。过去它无条件再导出整座协作模板半区，
而 Python 导入子包必先执行父包 `__init__` ——于是任何一次 `import neurova.collaborate.workflow.scheduler`
都连带执行那 863 行从未接线的死码，既是每次启动的真实成本，也向下一个人暗示"这里有协作实现"。

现役实现归属（退役时逐条验过实质，不是"存在即替代"）：
- 协作模板 / 角色 / 步骤 schema ＝ `neurova/agent/templates/collaboration_template.py`，
  真消费链在 `neurova/agent/team.py`；本包那份与之 350 行里 346 行相同，是纯双源的死支。
- 流程编排 ＝ `neurova/collaboration/neurflow/*`。
- 定时与触发 ＝ 本包 `workflow/scheduler.py`（`api/endpoints/scheduler.py` 与 `agent_package.py` 在用）。
"""

from .workflow import (
    AgentScheduler,
    FlowContext,
    ScheduledTask,
    compute_next_run,
    get_scheduler,
    register_action_handlers,
)

__all__ = [
    "AgentScheduler",
    "FlowContext",
    "ScheduledTask",
    "compute_next_run",
    "get_scheduler",
    "register_action_handlers",
]
