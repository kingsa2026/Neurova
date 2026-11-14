"""受限脚本化工作流（P3-14）。

对照 ZCode dynamic-workflow：模型写受限脚本，引擎做静态检查、子进程隔离
执行、journal 落盘可续跑——用「模型写脚本、宿主管执行」替代自由 agent
循环跑长任务。Neurova 形态：

- 脚本 = ``async def main(ctx)``；静态白名单（禁 import/危险内建/dunder/
  global）经 AST 校验（解析走全仓唯一出口），父侧校验＋子进程内二次校验
  （纵深防御）；
- 执行在**独立子进程**（runner.py）：即便白名单被绕过，子进程也无法触碰
  父进程状态；超时直接终止子进程；
- 副作用只能经 NDJSON 桥 ``ctx.callTool`` 请求父侧，由父侧走**完整治理
  管线**（审批/审计不旁路）并逐调用 journal 落盘；
- 续跑（resume_run_id）：账本里已留痕的调用按序复用结果，不重复执行副作用。
"""

from neurova.workflow.scripted.engine import runScriptedWorkflowSubprocess
from neurova.workflow.scripted.journal import WorkflowJournal
from neurova.workflow.scripted.validator import validateScript

__all__ = [
    "WorkflowJournal",
    "runScriptedWorkflowSubprocess",
    "validateScript",
]
