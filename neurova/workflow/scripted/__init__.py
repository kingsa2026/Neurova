"""受限脚本化工作流（P3-14）。

对照 ZCode dynamic-workflow：模型写受限脚本，引擎做静态检查、受限执行、
journal 落盘可续跑——用「模型写脚本、宿主管执行」替代自由 agent 循环跑
长任务。Neurova 形态：

- 脚本 = ``async def main(ctx)``；静态白名单（禁 import/危险内建/dunder/
  global）经 AST 校验（解析走全仓唯一出口）；
- 副作用只能经 ``ctx.callTool`` 走**完整治理管线**（审批/审计不旁路）；
- journal（JSONL）逐调用落盘；续跑复用已留痕结果，不重复执行副作用。
"""

from neurova.workflow.scripted.engine import ScriptHost, runScriptedWorkflow
from neurova.workflow.scripted.journal import WorkflowJournal
from neurova.workflow.scripted.validator import validateScript

__all__ = [
    "ScriptHost",
    "WorkflowJournal",
    "runScriptedWorkflow",
    "validateScript",
]
