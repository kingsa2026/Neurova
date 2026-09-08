"""Plan Mode —— 计划模式（ZCode 对齐）

交互式计划工作流：
/start（首轮问题）→ N 轮问答（不限轮数，支持自由补充）→ LLM 生成计划
→ MD 落盘 agent 工作目录 docs/plan/<时间戳>-<标题>.md → 审批
（approve 返回注入计划全文的 execute_prompt，由前端走聊天原链路执行；
 reject 终结）。

模块组成：
- PlanDocStore  — MD 计划文档落盘/读取/列表（agent_workspaces/<agent_id>/docs/plan/）
- PlanSession   — 单个计划会话状态机（asking → awaiting_approval → approved/rejected）
- PlanSessionManager — 会话注册表（归属隔离 + TTL 过期 + 单例）

隔离语义：会话与文档按 (agent_id, user_id) 二维归属隔离（与 PlanStore /
KnowledgeGraph per-agent 同基座）；文档按 agent 隔离，会话按 user 隔离。
"""

from neurova.plan_mode.errors import (
    PlanDocError,
    PlanDocNotFound,
    PlanError,
    PlanLLMError,
    PlanStateError,
)
from neurova.plan_mode.plan_docs import (
    PlanDocStore,
    get_plan_doc_store,
    reset_plan_doc_store,
)
from neurova.plan_mode.plan_session import (
    PlanSession,
    PlanSessionManager,
    get_plan_session_manager,
    reset_plan_session_manager,
)

__all__ = [
    "PlanDocError",
    "PlanDocNotFound",
    "PlanDocStore",
    "PlanError",
    "PlanLLMError",
    "PlanSession",
    "PlanSessionManager",
    "PlanStateError",
    "get_plan_doc_store",
    "reset_plan_doc_store",
    "get_plan_session_manager",
    "reset_plan_session_manager",
]
