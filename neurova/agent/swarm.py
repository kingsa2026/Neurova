"""
SwarmManager — 蜂群编排核心（主 Agent 动态派生子 Agent）

主 Agent 在对话/工作流中通过 spawn 工具动态派生子 Agent
执行子任务，可并行（多次调用）、可后台（background=True）。

输出回流三通道：
1. 直传（主通道）：最终报告作为工具结果返回主 Agent，同时经 SessionSyncManager
   广播 SUBAGENT_STARTED / SUBAGENT_CHUNK / SUBAGENT_COMPLETED 到聊天会话
   （前端子 Agent 对话小窗的数据源）
2. 池归档（辅助通道）：报告归档进发起者 Agent 的上下文池（EXPERIENCE 源），
   供后续轮次语义召回（活水）
3. 终态回灌（对话侧通道）：终态（完成/失败/超时/取消）以**信封**投递发起者会话的
   AgentMailbox，由 agent loop 在工具轮间隙以 user 角色排空注入——后台派生的
   唯一回传通道。投递绑在**子任务终态**，不绑在 spawn() 返回处：后台那一刻还没有
   任何终态可投。仅 chat 来源（workflow 的报告交给引擎 output）。

旁路两条出口（邮箱、上下文池归档）投**同一份** `_uplinkEnvelope()` 投影：只带关键
信息与 transcript 指针，不搬正文、也不按字面量截断。主 Agent 要看详情，凭指针经
`recall_history(agent_id, session_id)` 下钻到记录该子任务全过程的会话 json；报告
全文由主链路（工具返回值 `to_dict()` 的 `report` 键）同轮送达。

设计约束（AGENTS.md）：
- 深模块：延迟导入 Agent 注册中心（neurova.api.endpoints），避免循环依赖
- 子 Agent 故障隔离：异常捕获为失败结果，不向上抛
- 单例生命周期: get_swarm_manager() / reset_swarm_manager()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from neurova.agent.task_unit import parseTaskUnit, renderTaskUnitPrompt
from neurova.agent.acceptance_gate import runAcceptanceLoop
from neurova.agent.review_gate import runReviewLoop
from neurova.agent.context_firewall import buildDataFence
from neurova.core.lazy_singleton import lazySingleton
from neurova.core.trace_context import get_trace_id

logger = logging.getLogger(__name__)

# 事件发射器签名：(event_type, data) -> None，event_type ∈ {"content", "reasoning"}
StreamEmitter = Callable[[str, Any], None]

# 当前正在执行的 member 所在深度（顶层用户会话 = 0）。派生深度 = 本值 + 1。
#
# 为什么不挂 Agent 实例：Agent 是进程级单例（AppState.agents 共享池），同一
# agent_id 既可能作为某条链的 member，也可能被另一个顶层会话直接使用——实例
# 属性存深度会在并发链间互踩（与切片 A「轮次态不得挂单例」同一条根因）。
# 存 ContextVar：`_run_member` 在子 Agent 的 `chat` 之前按 run.depth 绑定、
# 之后复位；member 内的 `spawn_subagent` 读到的就是它自己那条链的深度。
# 后台派生走 `asyncio.create_task`（拷贝当前上下文），绑定发生在创建任务**之后**、
# 子 Agent chat **之前**，故后台链同样读到正确深度。
_subagentDepthVar: ContextVar = ContextVar("neurova_subagent_depth", default=0)


def current_subagent_depth() -> int:
    """当前执行上下文所在的派生深度（顶层 = 0）。"""
    return int(_subagentDepthVar.get() or 0)


def set_subagent_depth(depth: int):
    """绑定当前执行的派生深度，返回 token 供复位。"""
    return _subagentDepthVar.set(int(depth))


def reset_subagent_depth(token) -> None:
    """复位派生深度到绑定前（token 由 set_subagent_depth 返回）。"""
    _subagentDepthVar.reset(token)


# ── 子任务状态词汇的唯一出处（§6-78 K 条）──────────────────────────
# 改前这六个词值散在本文件六处（dataclass 默认、返回投影、list_active、
# _count_active、_evict_finished_runs、归档判定），**没有一份定义**：计数说
# pending/running 是「运行中」，逐出说 completed/failed 是「结束」，两条各自手抄——
# 于是一条停在 running 的卡死件既不算「可逐出」也永远算「占槽」，5 条就把蜂群锁死。
# 现两处集合由同一份词值导出，互斥且并起来覆盖整个状态域（判据钉这条）。
SUBAGENT_PENDING = "pending"
SUBAGENT_RUNNING = "running"
#: P1-3（评测报告 G-5）：监督评审相位——验收通过后、终态前的把关段（占派生槽）
SUBAGENT_IN_REVIEW = "in_review"
SUBAGENT_COMPLETED = "completed"
SUBAGENT_FAILED = "failed"
SUBAGENT_STATUSES = frozenset(
    {SUBAGENT_PENDING, SUBAGENT_RUNNING, SUBAGENT_IN_REVIEW, SUBAGENT_COMPLETED, SUBAGENT_FAILED})
#: 仍占着派生槽、且永不逐出的状态
SUBAGENT_ACTIVE_STATUSES = frozenset({SUBAGENT_PENDING, SUBAGENT_RUNNING, SUBAGENT_IN_REVIEW})
#: 已收尾的状态——既释放槽位，也进 _evict_finished_runs 的逐出面
SUBAGENT_FINISHED_STATUSES = frozenset({SUBAGENT_COMPLETED, SUBAGENT_FAILED})

#: 运行窗口预算的覆盖入口；**默认值不写在蜂群里**，取 `tool_coordinator` 的
#: `spawn_subagent` 那份读数（同一件事只许有一个尺度，见 `_effectiveRuntimeBudget`）
SUBAGENT_BUDGET_ENV = "NEUROVA_SWARM_SUBAGENT_BUDGET_SEC"

#: 前台自动转后台的定时器（秒；P2 蜂群对照 #4）。>0 时前台派生若在窗口内
#: 未跑完，即脱离父 turn 转后台继续（返回 background 信封 + subagent_id，
#: 终态仍走既有邮箱/广播回灌），父会话不再被长任务阻塞到预算墙。
#: 0/未设 = 关闭（保持既有"前台等到底"语义）。
AUTO_BACKGROUND_ENV = "NEUROVA_SWARM_AUTO_BACKGROUND_AFTER_S"

#: 卡死渐进提醒（P2 蜂群对照 #5）：member 连续无产出达到首报阈值即提醒
#: （广播 subagent_stalled + 父会话邮箱），此后按指数退避续报、封顶上限。
#: **发现而不裁决**——只提醒，等/停由主代理决定。首报默认 900s，
#: 0 = 关闭；上限默认 14400s（4h）。
STALL_FIRST_REMINDER_ENV = "NEUROVA_SWARM_STALL_FIRST_S"
STALL_REMINDER_CAP_ENV = "NEUROVA_SWARM_STALL_CAP_S"
STALL_FIRST_REMINDER_DEFAULT_S = 900.0
STALL_REMINDER_CAP_DEFAULT_S = 14400.0
# 收尾成因的常量由台账侧持有（`agent_run_ledger`），swarm 只引用不自造第二份：
# 台账的 error_type 与这里的 cause 必须是同一批词值。
from neurova.core.agent_run_ledger import (
    SUBAGENT_CAUSE_CANCELLED, SUBAGENT_CAUSE_TIMEOUT,
)


def mcpBorrowedToolNames() -> frozenset:
    """P3（蜂群对照 #8）：父上下文当前可用的 MCP 工具名快照（借用面）。

    进程级 MCP 客户端单例的已缓存工具即"父能用的 MCP 面"；子代理与父同身份
    执行，执行期仍走 MCP 既有授权/防火墙管线——借用只放行**调用面**，
    MCP 生命周期管理（装/卸/启停插件）本就是内置工具，不在 mcp.* 命名空间。
    fail-open：枚举失败回空集（不借，收窄不失守）。
    """
    try:
        from neurova.tool_layers.mcp_client import get_mcp_client

        client = get_mcp_client()
        if client is None:
            return frozenset()
        names = set()
        for tool in client.list_tools() or []:
            raw = str((tool or {}).get("name") or "").strip()
            server = str((tool or {}).get("server_id") or "").strip()
            if raw:
                names.add(raw)
                if server:
                    names.add(f"mcp.{server}.{raw}")
        return frozenset(names)
    except Exception:  # noqa: BLE001 - MCP 面不可枚举时不借
        return frozenset()


def computeSubagentToolAllowlist(
    subagentType: str, borrowMcp: frozenset = frozenset()
) -> frozenset:
    """按子代理类型计算工具面白名单（P1 蜂群对照；spawn 与测试共用的单一出口）。

    - general：全量内置工具 − 递归派生/续跑（子代理不得再派生孙代理，
      也不得续跑兄弟——两者都是"从子代理回合里再拉起一条执行链"）；
      可选借用父上下文的 MCP 调用面（``borrowMcp`` 快照，P3 #8）；
    - explore：只读白名单（检索/侦察型子代理不拿写工具，也不借 MCP）。
    执行咽喉（ToolExecutor._execute_single_tool）据 member 上下文绑定的
    白名单强制拦截面外工具。
    """
    from neurova.builtin_tools import (
        get_builtin_tool_capability,
        get_registered_tool_names,
    )

    if str(subagentType or "").strip().lower() == "explore":
        readonlyNames = []
        for toolName in get_registered_tool_names():
            cap = get_builtin_tool_capability(toolName)
            if cap is not None and getattr(cap, "readOnly", False):
                readonlyNames.append(toolName)
        return frozenset(readonlyNames)
    # general：全量内置工具 − 递归派生/续跑（子代理不得再派生孙代理，
    # 也不得续跑兄弟——两者都是"从子代理回合里再拉起一条执行链"）；
    # − 审批裁决（P3-1：子代理不得裁决自己发起的审批单——自己批自己=审批链失效）
    base = frozenset(get_registered_tool_names()) - {
        "spawn_subagent", "continue_subagent", "decide_subagent_approval",
    }
    return base | frozenset(borrowMcp)


@dataclass
class SubAgentRun:
    """一次子 Agent 运行的状态记录"""

    subagent_id: str = field(default_factory=lambda: f"swarm_{uuid.uuid4().hex[:12]}")
    agent_id: str = ""
    agent_name: str = ""
    task: str = ""
    model: str = ""  # 派生目标模型名（解析失败为 ""）——预算/并发/冷却治理据此判定
    origin: str = "chat"  # chat | workflow
    depth: int = 1  # 派生深度（顶层派生的子 Agent 为 1；member 内再派生递增）
    session_id: Optional[str] = None  # 事件广播目标（发起者的聊天会话）
    # P2-9：member 会话键。
    # member 的任务对话经既有 save_to_session → SessionManager.add_message
    # 持久化到 <数据根>/<agent_id>/sessions/session_<member_session_id>_<日期>.json
    # （落点由 `SessionManager._get_session_dir` 解析——活体实测过，别按字面拼路径去找它），
    # 完全复用单 agent 会话存储/历史恢复/usage 记账——不建第二套管线。
    # Windows 文件名安全。
    member_session_id: str = ""
    # P1（蜂群对照）：子代理类型（general/explore）与工具面白名单——
    # 派生时按类型收窄，member 任务上下文绑定，执行咽喉强制拦截。
    subagent_type: str = "general"
    tool_allowlist: Optional[frozenset] = None
    # P1-1（评测报告 G-2）：结构化任务单元（TaskUnit.toDict()）——验收/评审/依赖门的数据基础。
    # None = 未提供（自由文本派生，向后兼容）。
    task_unit: Optional[Dict[str, Any]] = None
    # P1-2（评测报告 G-3）：验收门判定记录（achieved/missing/rounds/reworked 或 skipped）。
    # None = 未过门（开关关且无显式验收条件）。
    acceptance: Optional[Dict[str, Any]] = None
    # P1-3（评测报告 G-5）：监督评审记录（passed/findings/rounds/reworked 或 skipped）。
    # None = 未评审（reviewMode != supervisor）。
    review: Optional[Dict[str, Any]] = None
    # P3-1（评测报告 G-11）：运行中审批请求记录（request_approval 工具写入，
    # approval_chain.requestRunApproval 落账）——谁在何时请求了什么、裁决到哪一步。
    approvals: List[Dict[str, Any]] = field(default_factory=list)
    # P3-2（评测报告 G-12）：span 级 trace——parent_trace_id 是发起请求那一刻的
    # 请求级 trace（spawn 时刻从 ContextVar 捕获，可为空）；trace_id 是 member
    # 执行期自己开设的轨迹（台账行经 agent_runs.trace_id 与之关联）。
    parent_trace_id: str = ""
    trace_id: str = ""
    # P3-4（评测报告 G-13）：数据面围栏扫描摘要（task_hits/payload_hits/hit_count）。
    # None = 未命中（干净任务不留标记噪音）；命中只标记与告警，不改写不阻断。
    data_fence: Optional[Dict[str, Any]] = None
    status: str = SUBAGENT_PENDING  # 取值域见 SUBAGENT_STATUSES（本模块常量，唯一出处）
    # P2-10 增强：子代理升级/结构化结果提交（escalate/submit_result 工具写入，
    # 随邮箱投递发起者会话；只作读数与通知，不改变运行状态机）
    escalation: Optional[Dict[str, Any]] = None
    submitted_result: Optional[Dict[str, Any]] = None
    # 收尾成因（见 `agent_run_ledger.SUBAGENT_CAUSE_*`）：台账的 error_type 由它翻出来，
    # 不靠嗅探 error 文本——那正是「同一件事两份口径」的下一种形态。
    cause: str = "" 
    report: str = ""
    error: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    node_id: Optional[str] = None  # workflow 来源时的节点 id
    execution_id: Optional[str] = None  # workflow 来源时的执行 id
    # P2（工具清单 3.1-3 续）：复活来源——本条 run 是对哪条终态 run 的续跑
    # （continue_subagent 写入；空串 = 全新派生）。member 会话复用被续跑那条的
    # 键，子 Agent 的历史由既有会话恢复机制带回，不另造第二套状态搬运。
    resumed_from: str = ""
    # P2（蜂群对照 #5）：卡死时钟的进度位——member 最近一次"有产出迹象"的
    # 单调时刻（run 启动 / 流式 chunk 到达都算）。看门狗据此判 stall。
    last_progress_at: float = field(default_factory=time.monotonic)
    stall_reminder_count: int = 0
    # 运行时状态：预留的模型并发槽（None=未占用）；_execute 的 finally 据此释放
    slot_model: Optional[str] = field(default=None, repr=False)

    @property
    def duration(self) -> float:
        if self.finished_at:
            return self.finished_at - self.started_at
        return time.time() - self.started_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subagent_id": self.subagent_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "task": self.task,
            "model": self.model,
            "origin": self.origin,
            "depth": self.depth,
            "session_id": self.session_id,
            "member_session_id": self.member_session_id,
            "subagent_type": self.subagent_type,
            "task_unit": self.task_unit,
            "acceptance": self.acceptance,
            "review": self.review,
            "approvals": list(self.approvals),
            "parent_trace_id": self.parent_trace_id,
            "trace_id": self.trace_id,
            "data_fence": self.data_fence,
            "escalation": self.escalation,
            "submitted_result": self.submitted_result,
            "tool_allowlist_size": len(self.tool_allowlist) if self.tool_allowlist else None,
            "status": self.status,
            "report": self.report,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": self.duration,
            "node_id": self.node_id,
            "execution_id": self.execution_id,
            "resumed_from": self.resumed_from,
        }


def _settingsDefaultSubagentDepth() -> int:
    """深度上限的默认值：**取自** `agent_limits_settings.DEFAULTS` 单源。

    本函数只是把单源的值搬进类属性（供设置不可读时的 `_effective_max_depth()`
    回落），不在此手抄第二份数字。单源不可导入是真实故障，交给 import 出声，
    不吞异常改成静默常量。
    """
    from neurova.security.agent_limits_settings import DEFAULTS

    return int(DEFAULTS["max_subagent_depth"])


class SwarmManager:
    """蜂群管理器：派生、执行、事件广播、结果回流

 spawn 三明治治理——LLM 自主繁殖子 agent 时
    "提示词约束必然被忽略"，由数据层硬拒绝兜底：
    - 常量硬限：MAX_ACTIVE_CHILDREN / MAX_TASK_CHARS（本类属性，数据层
      消费方不可绕过）
    - 结构化拒绝：spawn() 返回 {rejected: True, rejection: {code, message}}，
      is_policy_denial 识别 swarm_rejection 标记（决策非故障，不计熔断）
    - 配额闭环：返回值带 active_children / limit；工具描述内嵌配额纪律
      （builtin_tools.py spawn_subagent schema，第三层提示词纪律）
    """

    # P2-10 修复: 已完成 run 的保留上限。超出后按完成时间从最旧逐出，
    # 防止 _runs 随派生次数无界增长导致长期运行内存泄漏。
    # 运行中（pending/running）的 run 永不逐出；status() 查询已逐出的
    # 历史记录返回"未找到"（与从未存在等价，可接受）。
    MAX_FINISHED_RUNS = 500

    # ── spawn 三明治之常量硬限（数据层） ──────────────────────────
    # 同时运行中的派生上限（pending/running 全局口径；桌面单用户产品的
    # 进程保护阀门，member 内递归派生同受此限）
    MAX_ACTIVE_CHILDREN = 5
    # 单个 task 长度上限（防 LLM 把整段对话历史塞进 task 拖垮子 Agent）
    MAX_TASK_CHARS = 8000
    # ── spawn 三明治之深度契约 ────────────────────────────────────
    # 派生链的**深度**上限（不是广度）。广度（同时运行中的子 Agent 数）由
    # MAX_ACTIVE_CHILDREN 守；深度（一条链能嵌几层）必须独立声明——否则它只是
    # "全局广度帽跑满之前先撞上"的偶发现象，随兄弟数量读出不同层数（切片 D 根因）。
    # 这是设置不可读时的**兜底值**，且它**取自** `agent_limits_settings.DEFAULTS`
    # 单源（`_settingsDefaultSubagentDepth()`）——不在此手抄第二份数字。
    # 生效值仍由 `_effective_max_depth()` 经设置层读取。
    MAX_SUBAGENT_DEPTH = _settingsDefaultSubagentDepth()

    # ── fan-out 治理（吸收进 spawn 三明治，防成本/限流踩踏；0=关闭保持既有突发语义）──
    # 同一模型的并发子 Agent 上限（"大模型并发帽"）
    MAX_CONCURRENT_PER_MODEL = int(os.environ.get("NEUROVA_SWARM_MAX_CONCURRENT_PER_MODEL", "0") or 0)
    # 连续两次派生的最小间隔（毫秒，确定性错峰防惊群）
    MIN_SPAWN_INTERVAL_MS = int(os.environ.get("NEUROVA_SWARM_MIN_SPAWN_INTERVAL_MS", "0") or 0)

    def __init__(self):
        self._runs: Dict[str, SubAgentRun] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._model_active: Dict[str, int] = {}  # 每模型并发子 Agent 计数（自持，不与共享限流器双计）
        self._last_dispatch_ts: float = 0.0       # 上次通过治理闸的派生时刻（monotonic，错峰用）
        # P1-4（评测报告 G-4）：依赖未就绪的派生请求（subagent_id → 启动信息）。
        # 不占派生槽、不入 _runs；依赖终态结算时放行或判失败。status() 可查。
        self._blocked: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    # ── 公共接口 ──────────────────────────────────────────────

    async def spawn(
        self,
        task: str,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        background: bool = False,
        origin: str = "chat",
        stream: bool = True,
        initiator_agent: Optional[Any] = None,
        node_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        subagent_type: str = "general",
        task_unit: Optional[dict] = None,
        reuse_member_session_id: Optional[str] = None,
        resumed_from: Optional[str] = None,
    ) -> Dict[str, Any]:
        """派生子 Agent 执行任务

        Args:
            task: 交给子 Agent 的完整任务描述
            agent_id: 目标子 Agent ID；None 用 default；不存在回退 default
            session_id: 聊天会话 ID（事件广播目标；None 则不广播）
            background: True 后台执行（立即返回 subagent_id）
            origin: 来源（chat | workflow），用于事件追踪
            stream: True 时子 Agent 的 content/reasoning 逐 chunk 广播
            initiator_agent: 发起者 Agent 实例（用于结果归档进其上下文池）
            node_id / execution_id: workflow 来源时的定位信息
            reuse_member_session_id: 复用既有 member 会话键（续跑用——子 Agent
                的历史由既有会话恢复机制带回）；None 新建
            resumed_from: 被续跑的 subagent_id（溯源读数；空 = 全新派生）

        Returns:
            前台: {subagent_id, agent_id, agent_name, status, report, duration, ...}
            后台: {subagent_id, agent_id, agent_name, status: "pending", background: True}
        """
        if not task or not str(task).strip():
            return {"error": "task 不能为空"}

        # P1-1（评测报告 G-2）：结构化任务单元——解析失败走结构化拒绝（决策非故障）
        try:
            parsedUnit = parseTaskUnit(task_unit)
        except ValueError as exc:
            return self._rejection("TASK_UNIT_INVALID", f"task_unit 非法：{exc}")

        # ── 三明治之数据层结构化拒绝（先于一切派生动作） ──────────
        task = str(task)
        if len(task) > self.MAX_TASK_CHARS:
            return self._rejection(
                "TASK_TOO_LARGE",
                f"task 长度 {len(task)} 超过硬限 {self.MAX_TASK_CHARS}——"
                "请压缩为自包含的子任务描述，不要把对话历史整段塞入",
            )
        child_depth = current_subagent_depth() + 1
        max_depth = self._effective_max_depth()
        if child_depth > max_depth:
            return self._rejection(
                "SUBAGENT_DEPTH_EXCEEDED",
                f"派生深度 {child_depth} 超过上限 {max_depth}——"
                "子 Agent 不得在链上无限嵌套派生；请把子任务拆成并列的兄弟任务，"
                "或由顶层直接派生",
            )

        active_children = self._count_active()
        if active_children >= self.MAX_ACTIVE_CHILDREN:
            # 文案承诺「等待完成」就必须给出上界，否则调用方（LLM）只能无限等——
            # K 条里那 5 条卡死件根本不会完成。上界与执行侧取同一份读数，不重抄数字。
            return self._rejection(
                "MAX_ACTIVE_CHILDREN",
                f"运行中的子 Agent 已达硬限 {self.MAX_ACTIVE_CHILDREN}——"
                f"每条子任务最长 {self._effectiveRuntimeBudget():g}s 内必落终态"
                "（完成/失败/超时/取消都收尾并释放槽位），"
                "请用 subagent_status 查询后再派生",
                active_children=active_children,
            )

        agent, resolved_id, fallback = self._resolve_agent(agent_id)
        if agent is None:
            return {"error": f"未找到可用的子 Agent（请求: {agent_id or 'default'}）"}

        model = self._resolve_model_name(agent)
        cap = self.MAX_CONCURRENT_PER_MODEL

        # ── fan-out 治理闸（预算/冷却/并发/间隔；全部 fail-open，可 kill-switch）──
        if self._governance_enabled():
            if self._over_budget(resolved_id, model):
                return self._rejection(
                    "BUDGET_EXCEEDED",
                    f"agent {resolved_id} 预算已超支——暂缓派生子 Agent，等待配额重置或提升预算",
                )
            cooldown = self._model_cooldown_remaining(model)
            if cooldown > 0:
                return self._rejection(
                    "MODEL_COOLDOWN",
                    f"模型 {model} 正处 429 退避冷却（剩余 {cooldown:.1f}s）——暂缓派生以避开上游限流",
                    retry_after_ms=int(cooldown * 1000),
                )

        if cap and cap > 0 and model:
            with self._lock:
                if self._model_active.get(model, 0) >= cap:
                    return self._rejection(
                        "MODEL_CONCURRENCY",
                        f"模型 {model} 并发子 Agent 已达上限 {cap}——错峰派生，等待现有同类子任务完成",
                    )

        interval = self.MIN_SPAWN_INTERVAL_MS
        if interval and interval > 0:
            with self._lock:
                elapsed_ms = (time.monotonic() - self._last_dispatch_ts) * 1000.0
                if elapsed_ms < interval:
                    return self._rejection(
                        "SPAWN_TOO_FAST",
                        f"派生过快（距上次 {elapsed_ms:.0f}ms < {interval}ms）——确定性错峰防惊群",
                        retry_after_ms=int(interval - elapsed_ms),
                    )

        if subagent_type not in ("general", "explore"):
            return self._rejection(
                "SUBAGENT_TYPE_UNKNOWN",
                f"未知子代理类型 {subagent_type!r}（可选 general/explore）",
            )
        # P3（蜂群对照 #8）：general 型借用父上下文的 MCP 调用面（spawn 时刻
        # 快照冻结进 run.tool_allowlist）；explore 型不借（只读白名单保持纯内置）。
        toolAllowlist = computeSubagentToolAllowlist(
            subagent_type,
            borrowMcp=mcpBorrowedToolNames() if subagent_type == "general" else frozenset(),
        )

        # P3-4（评测报告 G-13）：数据面围栏——任务文本与不可信槽位做注入特征扫描，
        # 命中只标记与告警（不改写任务文本、不阻断派生主链路，处置权在主代理/用户）
        dataFence = buildDataFence(task, parsedUnit.untrustedPayload if parsedUnit else "")
        if dataFence["hit_count"]:
            logger.warning(
                "Swarm: 数据面围栏命中注入特征 run_task=%r task_hits=%s payload_hits=%s",
                task[:120],
                [(h["pattern"], h["excerpt"]) for h in dataFence["task_hits"]],
                [(h["pattern"], h["excerpt"]) for h in dataFence["payload_hits"]],
            )

        # P1-4（评测报告 G-4）：依赖门控——dependencies 只能指向已存在的 run
        #（结构性防环：run 按创建序存在，后者不可依赖前者之外的 id）。未满足的
        # 依赖 → 登记为 blocked（不占派生槽），终态结算时自动放行或判失败。
        deps = parsedUnit.dependencies if parsedUnit else []
        if deps:
            unknown = [d for d in deps if d not in self._runs]
            if unknown:
                return self._rejection(
                    "DEPENDENCY_UNKNOWN",
                    f"依赖的 subagent_id 不存在（或已逐出）: {unknown}——"
                    "依赖只能指向已派生的子任务，且须在派生时声明",
                )
            if len(set(deps)) != len(deps):
                return self._rejection("DEPENDENCY_DUPLICATED", f"依赖项重复: {deps}")
            # 前置已终态且未验收通过（失败/取消/验收不达标）→ 即时拒绝：
            # 终态结算只发生在终态迁移那一刻，已终结的前置不会再触发结算，
            # 此时登记 blocked 就是永久等待——直接拒绝才诚实（η 门：失败产出不是合格输入）
            failedDeps = [d for d in deps
                          if self._runs[d].status in SUBAGENT_FINISHED_STATUSES
                          and not self._depSatisfied(self._runs[d])]
            if failedDeps:
                return self._rejection(
                    "DEPENDENCY_FAILED",
                    f"依赖的前置未验收通过: {failedDeps}——请修复/重派前置后重新派生本任务",
                )
            unsatisfied = [d for d in deps if not self._depSatisfied(self._runs[d])]
            if unsatisfied:
                blockedId = f"swarm_{uuid.uuid4().hex[:12]}"
                with self._lock:
                    self._blocked[blockedId] = {
                        "subagent_id": blockedId, "task": task, "agent_id": resolved_id,
                        "agent_name": getattr(agent.config, "name", resolved_id) if hasattr(agent, "config") else resolved_id,
                        "session_id": session_id, "origin": origin, "stream": stream,
                        "initiator_agent": initiator_agent, "node_id": node_id,
                        "execution_id": execution_id, "subagent_type": subagent_type,
                        "task_unit": parsedUnit.toDict() if parsedUnit else None,
                        "tool_allowlist": toolAllowlist, "depth": child_depth,
                        "parent_trace_id": get_trace_id() or "",
                        "data_fence": dataFence,
                        "deps": list(deps), "status": "blocked", "created_at": time.time(),
                    }
            return {
                "subagent_id": blockedId, "agent_id": resolved_id,
                "status": "blocked", "background": True,
                "dependencies": list(deps), "unsatisfied": unsatisfied,
                "data_fence": dataFence,
                "hint": "依赖未就绪，已登记等待；依赖验收通过后自动启动（subagent_status 查询）",
                **self._quota_snapshot(),
            }

        run = SubAgentRun(
            depth=child_depth,
            agent_id=resolved_id,
            agent_name=getattr(agent.config, "name", resolved_id) if hasattr(agent, "config") else resolved_id,
            task=task,
            model=model or "",
            origin=origin,
            session_id=session_id,
            member_session_id=reuse_member_session_id or f"swarm_{uuid.uuid4().hex[:12]}",
            node_id=node_id,
            execution_id=execution_id,
            subagent_type=subagent_type,
            tool_allowlist=toolAllowlist,
            task_unit=parsedUnit.toDict() if parsedUnit else None,
            parent_trace_id=get_trace_id() or "",
            data_fence=dataFence if dataFence["hit_count"] else None,
            resumed_from=resumed_from or "",
        )
        # 通过全部治理闸 → 预留模型并发槽 + 打派生时间戳（错峰）
        with self._lock:
            # P2 §3.2-10: 上方 _count_active() 是无锁快查，与此处落账构成
            # check-then-act——并发派生可在两步之间突破硬限。权威判定挪进
            # 锁内原子化（_count_active 走 RLock 可重入），外层快查仅作快路径。
            activeNow = self._count_active()
            if activeNow >= self.MAX_ACTIVE_CHILDREN:
                return self._rejection(
                    "MAX_ACTIVE_CHILDREN",
                    f"运行中的子 Agent 已达硬限 {self.MAX_ACTIVE_CHILDREN}——"
                    f"每条子任务最长 {self._effectiveRuntimeBudget():g}s 内必落终态"
                    "（完成/失败/超时/取消都收尾并释放槽位），"
                    "请用 subagent_status 查询后再派生",
                    active_children=activeNow,
                )
            self._last_dispatch_ts = time.monotonic()
            if cap and cap > 0 and model:
                self._model_active[model] = self._model_active.get(model, 0) + 1
                run.slot_model = model
            self._runs[run.subagent_id] = run
            self._evict_finished_runs()

        if fallback:
            logger.info("Swarm: 请求的 agent_id=%s 不存在，回退到 %s", agent_id, resolved_id)

        quota = self._quota_snapshot()
        if background:
            asyncio_task = asyncio.create_task(
                self._execute(run, agent, initiator_agent, stream)
            )
            # P2-10 修复: 任务完成后移除引用，否则 _tasks 中的 asyncio.Task
            # （含协程栈与结果）随后台派生次数无界累积。
            asyncio_task.add_done_callback(
                lambda _task, _sid=run.subagent_id: self._forget_task(_sid)
            )
            with self._lock:
                self._tasks[run.subagent_id] = asyncio_task
            return {
                "subagent_id": run.subagent_id,
                "agent_id": run.agent_id,
                "agent_name": run.agent_name,
                "member_session_id": run.member_session_id,
                "status": SUBAGENT_PENDING,
                "background": True,
                "data_fence": dataFence,
                "hint": "使用 subagent_status 工具查询执行结果",
                **quota,
            }

        # P2（蜂群对照 #4）：前台自动转后台——窗口内跑完照常前台返回；
        # 没跑完即脱离父 turn 转后台继续（任务引用登记防 GC），终态仍走
        # 既有邮箱/广播回灌，父会话不再被长任务阻塞到预算墙。
        autoBgAfter = self._autoBackgroundSeconds()
        if autoBgAfter > 0:
            execTask = asyncio.create_task(
                self._execute(run, agent, initiator_agent, stream)
            )
            done, _pending = await asyncio.wait(
                {execTask}, timeout=autoBgAfter, return_when=asyncio.FIRST_COMPLETED
            )
            if execTask in done:
                return {**run.to_dict(), **self._quota_snapshot()}
            execTask.add_done_callback(
                lambda _task, _sid=run.subagent_id: self._forget_task(_sid)
            )
            with self._lock:
                self._tasks[run.subagent_id] = execTask
            return {
                "subagent_id": run.subagent_id,
                "agent_id": run.agent_id,
                "agent_name": run.agent_name,
                "member_session_id": run.member_session_id,
                "status": run.status,
                "background": True,
                "auto_background": True,
                "data_fence": dataFence,
                "hint": (
                    f"前台等待 {autoBgAfter:g}s 未完成已自动转后台"
                    "（subagent_status 查询；终态会自动回灌本会话）"
                ),
                **quota,
            }

        await self._execute(run, agent, initiator_agent, stream)
        return {**run.to_dict(), **self._quota_snapshot()}

    def _autoBackgroundSeconds(self) -> float:
        """前台自动转后台的窗口（秒）；0/未设 = 关闭（前台等到底）。"""
        raw = (os.environ.get(AUTO_BACKGROUND_ENV) or "").strip()
        try:
            return float(raw) if raw else 0.0
        except ValueError:
            return 0.0

    def status(self, subagent_id: str) -> Dict[str, Any]:
        """查询子 Agent 运行状态

        P1（2026-09-10）：subagent_id 可省略——前台 spawn 被工具层转后台时，
        信封里的 task_id（bg_xxx）查不了 swarm 记录，主 agent 需按最近列表
        主动轮询。列表与精确查询都给 report 全文（本工具是主链路，正文不砍），
        体量由条数界定，不按字面量截断长度。
        """
        if not (subagent_id or "").strip():
            return {
                "status": "list",
                "runs": self.list_all(limit=10),
                "hint": "最近派生的子 Agent（新→旧，report 全文）；精确查询请传 subagent_id",
            }
        with self._lock:
            run = self._runs.get(subagent_id)
            blocked = self._blocked.get(subagent_id)
        if run is None and blocked is None:
            return {"error": f"未找到子 Agent 运行记录: {subagent_id}"}
        if run is None:
            return dict(blocked)
        return run.to_dict()

    def list_active(self) -> List[Dict[str, Any]]:
        """列出未结束的子 Agent 运行"""
        with self._lock:
            runs = [r for r in self._runs.values() if r.status in SUBAGENT_ACTIVE_STATUSES]
        return [r.to_dict() for r in runs]

    def list_all(self, limit: int = 50) -> List[Dict[str, Any]]:
        """列出全部运行记录（新→旧）"""
        with self._lock:
            runs = sorted(self._runs.values(), key=lambda r: r.started_at, reverse=True)
        return [r.to_dict() for r in runs[:limit]]

    def pendingBackgroundForSession(self, session_id: Optional[str]) -> Dict[str, Any]:
        """H-2 机械完成闸门的判定输入：本会话还有哪些蜂群后台工作未清。

        活跃 run（pending/running/in_review，按发起会话过滤）+ 尚未回灌送达的
        邮箱件。供 loop 主出口在宣告完成前核账——发现而不裁决。
        """
        sid = str(session_id or "")
        active: List[Dict[str, Any]] = []
        with self._lock:
            for r in self._runs.values():
                if r.status in SUBAGENT_ACTIVE_STATUSES and r.session_id == sid:
                    active.append({
                        "subagent_id": r.subagent_id,
                        "status": r.status,
                        "task": (r.task or "")[:80],
                    })
        mailboxPending = 0
        if sid:
            try:
                from neurova.agent.mailbox import get_agent_mailbox

                mailboxPending = get_agent_mailbox().pending(sid)
            except Exception:  # noqa: BLE001 - 邮箱不可用不阻断核账
                pass
        return {
            "active": active,
            "mailbox_pending": mailboxPending,
            "pending": bool(active or mailboxPending),
        }

    def integrationReport(self) -> Dict[str, Any]:
        """P2-4（评测报告 G-6）：集成前核对面——各子任务验收/评审/依赖状态一览。

        η 门语义的读面：integration_ready=True 表示当前没有挂账的 blocker
        （失败/未验收/评审未过/依赖未满足的子任务）；主任务集成前应清零 blockers。
        """
        with self._lock:
            runs = list(self._runs.values())
            blocked = [dict(b) for b in self._blocked.values()]
        subtasks: List[Dict[str, Any]] = []
        blockers: List[Dict[str, Any]] = []
        for run in runs:
            acceptance = run.acceptance or {}
            review = run.review or {}
            item = {
                "subagent_id": run.subagent_id,
                "task": (run.task or "")[:80],
                "status": run.status,
                "cause": run.cause,
                "acceptance": acceptance.get("achieved"),
                "review": review.get("passed"),
            }
            subtasks.append(item)
            if run.status == SUBAGENT_FAILED:
                # 任何未成功收尾的子任务都是集成挂账（无论成因：执行失败/验收不达标/
                # 评审未过/依赖断供）——集成前必须逐一处置
                blockers.append({
                    "subagent_id": run.subagent_id,
                    "reason": run.cause or "failed",
                    "detail": (run.error or "")[:200],
                })
        for b in blocked:
            blockers.append({
                "subagent_id": b.get("subagent_id", ""),
                "reason": "dependencies_unsatisfied",
                "detail": f"等待依赖: {b.get('deps', [])}",
            })
        return {
            "integration_ready": not blockers,
            "blockers": blockers,
            "blocked_count": len(blocked),
            "subtasks": subtasks,
        }

    # ── P1-4（评测报告 G-4）：依赖门控 ──────────────────────────

    def _depSatisfied(self, run: SubAgentRun) -> bool:
        """依赖放行判据（η 门）：终态 completed 且验收门未判不达标。

        验收灰度关闭时 acceptance 为 None → 退化为"completed 即放行"（判据弱化但门仍在）；
        验收 failed/skipped-judge 的产出不是合格输入（skipped 是诚实降级，仍放行）。
        """
        if run.status != SUBAGENT_COMPLETED:
            return False
        acceptance = run.acceptance or {}
        return acceptance.get("achieved") is not False

    def _settleDependencies(self, run: SubAgentRun) -> None:
        """run 终态结算：判失败依赖未验收的下游；放行依赖已满足的 blocked 任务。"""
        if not self._blocked:
            return
        with self._lock:
            dependents = [bid for bid, info in self._blocked.items()
                          if run.subagent_id in info["deps"]]
            for bid in dependents:
                # 仅在判失败分支出账；放行分支留给 _promoteBlockedIfReady 统一 pop——
                # 否则条目在这里被删、promote 扑空，下游凭空消失（首版实测踩中）
                if not self._depSatisfied(run):
                    info = self._blocked.pop(bid)
                    self._failBlocked(bid, info, run)
        if self._depSatisfied(run):
            self._promoteBlockedIfReady()

    def _promoteBlockedIfReady(self) -> None:
        """放行依赖已满足的 blocked 任务（槽满则留待下次结算）。"""
        with self._lock:
            candidates = [bid for bid, info in self._blocked.items()
                          if all(d in self._runs and self._depSatisfied(self._runs[d])
                                 for d in info["deps"])]
        for bid in candidates:
            with self._lock:
                if self._count_active() >= self.MAX_ACTIVE_CHILDREN:
                    return  # 槽满：留待下一次终态结算再放行
                info = self._blocked.pop(bid)
            self._launchRun(info)

    def _launchRun(self, info: Dict[str, Any]) -> SubAgentRun:
        """把（blocked 放行的）启动信息落成 SubAgentRun 并异步执行。"""
        agent, resolved_id, _fallback = self._resolve_agent(info["agent_id"])
        model = self._resolve_model_name(agent) if agent is not None else ""
        run = SubAgentRun(
            subagent_id=info["subagent_id"],
            depth=info["depth"],
            agent_id=resolved_id,
            agent_name=info.get("agent_name") or resolved_id,
            task=info["task"],
            model=model or "",
            origin=info["origin"],
            session_id=info["session_id"],
            member_session_id=f"swarm_{uuid.uuid4().hex[:12]}",
            node_id=info["node_id"],
            execution_id=info["execution_id"],
            subagent_type=info["subagent_type"],
            tool_allowlist=info["tool_allowlist"],
            task_unit=info["task_unit"],
            parent_trace_id=info.get("parent_trace_id") or "",
            data_fence=info.get("data_fence") if (info.get("data_fence") or {}).get("hit_count") else None,
        )
        with self._lock:
            self._runs[run.subagent_id] = run
        execTask = asyncio.create_task(
            self._execute(run, agent, info["initiator_agent"], info["stream"])
        )
        execTask.add_done_callback(
            lambda _task, _sid=run.subagent_id: self._forget_task(_sid)
        )
        with self._lock:
            self._tasks[run.subagent_id] = execTask
        return run

    def _failBlocked(self, bid: str, info: Dict[str, Any], upstream: SubAgentRun) -> None:
        """依赖失败/未验收 → 下游不执行、不归档，直接以 failed 终态落账（η 门语义）。"""
        run = SubAgentRun(
            subagent_id=bid,
            depth=info["depth"],
            agent_id=info["agent_id"],
            agent_name=info.get("agent_name") or info["agent_id"],
            task=info["task"],
            origin=info["origin"],
            session_id=info["session_id"],
            node_id=info["node_id"],
            execution_id=info["execution_id"],
            subagent_type=info["subagent_type"],
            task_unit=info["task_unit"],
            parent_trace_id=info.get("parent_trace_id") or "",
            data_fence=info.get("data_fence") if (info.get("data_fence") or {}).get("hit_count") else None,
        )
        run.status = SUBAGENT_FAILED
        run.cause = "dependency_failed"
        run.error = (f"dependency_failed（前置 {upstream.subagent_id} 未验收通过："
                     f"{upstream.status}）；本任务未执行，请修复或重派前置后重新派生")
        run.finished_at = time.time()
        with self._lock:
            self._runs[bid] = run
            self._evict_finished_runs()


    async def resumeFinishedRun(
        self,
        subagentId: str,
        message: str,
        session_id: Optional[str] = None,
        initiator_agent: Optional[Any] = None,
        background: bool = False,
    ) -> Dict[str, Any]:
        """续跑一条已终态（completed/failed）的子 Agent（工具清单 3.1-3 续）。

        终态子 Agent 复活语义：member 会话键原样
        复用——子 Agent 上一段的对话历史由既有会话恢复机制带回，续跑不是从零
        重派；上一段的 report（失败时为部分交接件）附在续跑任务里作衔接上下文。
        治理闸（深度/广度/预算/冷却/并发/错峰）与全新派生走同一条 spawn 路径。
        """
        if not (subagentId or "").strip():
            return {"error": "subagent_id 不能为空"}
        if not (message or "").strip():
            return {"error": "message 不能为空——请带续跑指令"}
        with self._lock:
            old = self._runs.get(subagentId)
        if old is None:
            return {"error": f"未找到子 Agent 运行记录: {subagentId}"}
        if old.status not in SUBAGENT_FINISHED_STATUSES:
            return {
                "error": f"子 Agent {subagentId} 仍在运行（status={old.status}）——"
                         "续跑只针对已终态的运行；进行中的请用 subagent_status 等待",
            }
        handoff = old.report.strip()
        task = message.strip()
        if handoff:
            task = (
                f"[续跑衔接] 这是上一次执行的产出（{'失败前部分' if old.status == SUBAGENT_FAILED else '已完成部分'}），"
                f"供你衔接，不要从头重复：\n{handoff[:4000]}\n\n[续跑指令]\n{task}"
            )
        return await self.spawn(
            task,
            agent_id=old.agent_id,
            session_id=session_id if session_id is not None else old.session_id,
            background=background,
            origin="chat",
            stream=True,
            initiator_agent=initiator_agent,
            subagent_type=old.subagent_type,
            reuse_member_session_id=old.member_session_id,
            resumed_from=old.subagent_id,
        )

    # ── 内部实现 ──────────────────────────────────────────────

    def _effective_max_depth(self) -> int:
        """生效深度上限：单源在 `agent_limits_settings.max_subagent_depth`。

        配置不可读时回落到 `MAX_SUBAGENT_DEPTH` 常量——**不在此另立尺度**，
        常量只是设置层的兜底镜像（设置层自身也有内置默认）。
        """
        try:
            from neurova.security.agent_limits_settings import get_effective_limits

            return int(get_effective_limits().get("max_subagent_depth", self.MAX_SUBAGENT_DEPTH))
        except Exception:  # noqa: BLE001 - 设置不可读走常量兜底，不阻断派生
            return self.MAX_SUBAGENT_DEPTH

    @classmethod
    def _effectiveRuntimeBudget(cls) -> float:
        """一条子任务的运行窗口（秒）。**默认值不在蜂群自己手里**。

        仓内早已为这条链声明过尺度：`tool_coordinator.TOOL_TIMEOUTS_S["spawn_subagent"]
        = 600.0`（2026-09-10 蜂群超时排查落表，注释写明「前台 spawn 子任务动辄数分钟，
        60s 默认=必然转后台」）。改前的形态是：工具层 600s 就放弃等待，而 run 本身
        可以永远停在 `running`——两份口径的差正是 K 条的死锁来源。现两处读同一份数。

        `SUBAGENT_BUDGET_ENV` 可覆盖（运维调参与判据注入用），**每次调用现取**，
        不像 import 期烤死那样会让运行期调不动。取不到那份工具表读数时回落到
        工具层默认（`TOOL_DEFAULT_TIMEOUT_S`），仍不另造数字。
        """
        raw = (os.environ.get(SUBAGENT_BUDGET_ENV) or "").strip()
        if raw:
            try:
                return max(0.1, float(raw))
            except ValueError:
                logger.warning("Swarm: %s=%r 不是数字，回落工具层窗口读数",
                               SUBAGENT_BUDGET_ENV, raw)
        try:
            from neurova.agent.tool_coordinator import get_tool_timeout

            return float(get_tool_timeout("spawn_subagent"))
        except Exception:  # noqa: BLE001 - 工具层不可用不阻断派生，用其默认尺度
            from neurova.agent.tool_coordinator import TOOL_DEFAULT_TIMEOUT_S

            return float(TOOL_DEFAULT_TIMEOUT_S)

    def _count_active(self) -> int:
        """运行中（`SUBAGENT_ACTIVE_STATUSES`）派生数（含后台任务）。"""
        with self._lock:
            return sum(1 for r in self._runs.values() if r.status in SUBAGENT_ACTIVE_STATUSES)

    def _quota_snapshot(self) -> Dict[str, Any]:
        """配额闭环快照。"""
        return {
            "active_children": self._count_active(),
            "limit": self.MAX_ACTIVE_CHILDREN,
        }

    def _rejection(
        self, code: str, message: str, active_children: Optional[int] = None,
        retry_after_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        """数据层结构化拒绝（SpawnRejectReason 对应物）。

        swarm_rejection 标记键使 is_policy_denial 归类为"决策"而非
        "后端故障"——熔断器/失败统计不计数。retry_after_ms 供冷却/间隔类拒绝提示重试窗口。
        """
        payload: Dict[str, Any] = {
            "rejected": True,
            "swarm_rejection": True,
            "rejection": {"code": code, "message": message},
            "limit": self.MAX_ACTIVE_CHILDREN,
            "hint": "蜂群派生受数据层硬限保护；提示词纪律要求按需派生（未指定数量时每层 1-3 个）",
        }
        if active_children is not None:
            payload["active_children"] = active_children
        if retry_after_ms is not None:
            payload["retry_after_ms"] = int(retry_after_ms)
        return payload

    # ── fan-out 治理闸（预算/冷却/并发/间隔）──────────────────

    @staticmethod
    def _governance_enabled() -> bool:
        """治理总开关（kill-switch）：NEUROVA_SWARM_GOVERNANCE=off 关预算/冷却闸。"""
        return (os.environ.get("NEUROVA_SWARM_GOVERNANCE") or "on").strip().lower() != "off"

    @staticmethod
    def _resolve_model_name(agent: Any) -> Optional[str]:
        """尽力解析子 Agent 实际调用的模型名；非字符串/auto/缺失 → None（治理据此优雅跳过）。"""
        candidates = []
        for getter in (
            lambda: agent.llm_client.config.model,
            lambda: agent.model,
            lambda: agent.config.llm_config.model,
        ):
            try:
                candidates.append(getter())
            except Exception:  # noqa: BLE001 - 属性形态多样，取到即用
                continue
        for v in candidates:
            if isinstance(v, str) and v.strip() and v.strip().lower() != "auto":
                return v.strip()
        return None

    def _model_cooldown_remaining(self, model: Optional[str]) -> float:
        """只读探测模型 429 退避剩余秒数（复用共享限流器；不 acquire，避免双重计数）。"""
        if not model:
            return 0.0
        try:
            from neurova.llm.model_rate_limiter import get_shared_limiter

            return max(0.0, get_shared_limiter().pause_remaining(model))
        except Exception:  # noqa: BLE001 - 限流器不可用 → fail-open
            return 0.0

    def _over_budget(self, agent_id: str, model: Optional[str]) -> bool:
        """预算是否超支（读 record_llm_cost 写的同一单源；无预算 fail-open False）。"""
        try:
            from neurova.models.cost_budget import BudgetScope, get_budget_service

            mgr = get_budget_service().manager
            if agent_id and mgr.is_over_budget(BudgetScope.HOURLY, agent_id):
                return True
            if model and mgr.is_over_budget(BudgetScope.MODEL, model):
                return True
        except Exception:  # noqa: BLE001 - 预算不可用不阻断派生
            return False
        return False

    def _release_slot(self, run: SubAgentRun) -> None:
        """子 Agent 结束（成功/失败均）释放预留的模型并发槽，杜绝计数泄漏。"""
        model = getattr(run, "slot_model", None)
        if not model:
            return
        with self._lock:
            cur = self._model_active.get(model, 0)
            if cur <= 1:
                self._model_active.pop(model, None)
            else:
                self._model_active[model] = cur - 1
        run.slot_model = None

    def _forget_task(self, subagent_id: str) -> None:
        """移除已完成后台任务的引用（done 回调）"""
        with self._lock:
            self._tasks.pop(subagent_id, None)

    def _evict_finished_runs(self) -> None:
        """逐出超出保留上限的最旧已完成 run（调用方须持有 _lock）"""
        finished = [
            r for r in self._runs.values() if r.status in SUBAGENT_FINISHED_STATUSES
        ]
        overflow = len(finished) - self.MAX_FINISHED_RUNS
        if overflow <= 0:
            return
        finished.sort(key=lambda r: r.finished_at or r.started_at)
        for run in finished[:overflow]:
            self._runs.pop(run.subagent_id, None)

    def _resolve_agent(self, agent_id: Optional[str]) -> tuple:
        """解析子 Agent 实例；请求的 id 不存在时回退 default。

        Returns:
            (agent 实例或 None, resolved_id, 是否发生回退)
        """
        try:
            from neurova.api.endpoints import defaultAgentId, get_agent_instance

            if agent_id:
                agent = get_agent_instance(agent_id)
                if agent is not None:
                    return agent, agent_id, False

            # 回退位是**当前**默认 agent（可被 switch 改），不是字面量 "default"：
            # 返回的 resolved_id 必须与真正取到的那一位一致，否则上层按 id 记账时
            # 记到一个并非执行者的名字上。
            defaultId = defaultAgentId()
            default_agent = get_agent_instance(defaultId)
            if default_agent is not None:
                return default_agent, defaultId, bool(agent_id and agent_id != defaultId)

            # 兜底：注册表中取第一个可用实例
            state = None
            try:
                from neurova.api.endpoints import get_app_state

                state = get_app_state()
            except ImportError:
                pass
            if state:
                agents = state.get("agents", {})
                for aid, inst in agents.items():
                    if inst is not None:
                        return inst, aid, True
        except ImportError:
            logger.warning("Swarm: Agent 注册中心不可用（neurova.api.endpoints 未初始化）")
        return None, agent_id or "default", True

    async def _execute(
        self,
        run: SubAgentRun,
        agent: Any,
        initiator_agent: Optional[Any],
        stream: bool,
    ) -> None:
        """执行子 Agent：无论成功/失败，finally 释放其预留的模型并发槽（防泄漏）。"""
        # 卡死看门狗（发现而不裁决）：随 run 存活，终态即撤
        watchdog = asyncio.create_task(self._stallWatchdog(run))
        try:
            await self._run_member(
                run,
                agent,
                initiator_agent,
                stream,
                subagentType=run.subagent_type,
                toolAllowlist=run.tool_allowlist,
            )
        finally:
            watchdog.cancel()
            self._release_slot(run)
            # P1-4：终态结算——放行依赖已满足的 blocked 任务 / 判失败依赖未验收的下游
            self._settleDependencies(run)

    def _stallFirstSeconds(self) -> float:
        """卡死首报阈值（秒）；0 = 看门狗关闭。env 现取，默认 900s。"""
        raw = (os.environ.get(STALL_FIRST_REMINDER_ENV) or "").strip()
        try:
            return float(raw) if raw else STALL_FIRST_REMINDER_DEFAULT_S
        except ValueError:
            return STALL_FIRST_REMINDER_DEFAULT_S

    def _stallCapSeconds(self) -> float:
        """续报间隔的指数退避上限（秒），默认 4h。"""
        raw = (os.environ.get(STALL_REMINDER_CAP_ENV) or "").strip()
        try:
            return float(raw) if raw else STALL_REMINDER_CAP_DEFAULT_S
        except ValueError:
            return STALL_REMINDER_CAP_DEFAULT_S

    async def _stallWatchdog(self, run: SubAgentRun) -> None:
        """P2（蜂群对照 #5）：member 无产出渐进提醒。

        进度信号 = 流式 chunk 到达（emitter 触碰 last_progress_at）＋ run 启动。
        连续无产出达首报阈值即广播 subagent_stalled + 父会话邮箱提醒，
        此后阈值指数退避（15m→30m→60m…封顶 cap）。**只提醒不裁决**：
        等/停由主代理决定；run 状态机不受影响。
        """
        first = self._stallFirstSeconds()
        if first <= 0 or not run.session_id:
            return
        cap = max(first, self._stallCapSeconds())
        poll = max(1.0, min(30.0, first / 4))
        threshold = first
        while run.status in SUBAGENT_ACTIVE_STATUSES:
            await asyncio.sleep(poll)
            if run.status not in SUBAGENT_ACTIVE_STATUSES:
                return
            stalledFor = time.monotonic() - run.last_progress_at
            if stalledFor < threshold:
                continue
            run.stall_reminder_count += 1
            payload = {
                "subagent_id": run.subagent_id,
                "agent_name": run.agent_name,
                "stalled_seconds": int(stalledFor),
                "reminder_count": run.stall_reminder_count,
                "next_threshold_seconds": int(min(threshold * 2, cap)),
                "hint": "子代理长时间无产出；可继续等待（会再提醒）或派生替代任务",
            }
            await self._broadcast(run, "subagent_stalled", payload)
            self._notifyStallMail(run, payload)
            threshold = min(threshold * 2, cap)

    def _notifyStallMail(self, run: SubAgentRun, payload: Dict[str, Any]) -> None:
        """卡死提醒投父会话邮箱（与终态回灌同通道；失败不影响主流程）"""
        self.pushParentMail(run, "子Agent卡顿", {
            "kind": "subagent_stalled",
            "subagent_id": run.subagent_id,
            "agent_id": run.agent_id,
            "task": run.task,
            "stalled_seconds": payload["stalled_seconds"],
            "reminder_count": payload["reminder_count"],
            "member_session_id": run.member_session_id,
        })

    # ── P3-2（评测报告 G-12）：member span 级轨迹 ─────────────────

    @staticmethod
    def _traceEnabled() -> bool:
        """span 轨迹开关（kill-switch）：NEUROVA_SWARM_TRACE=off 关闭，默认开。"""
        return (os.environ.get("NEUROVA_SWARM_TRACE") or "on").strip().lower() != "off"

    def _startMemberTrace(self, run: SubAgentRun, userId: str) -> tuple:
        """开 member 轨迹与主 span，返回 (recorder, spanId)；关闭/故障返回 (None, None)。

        trace_id 落 run.trace_id（台账行经 agent_runs.trace_id 关联）；span 挂到
        轨迹根 span 成树；started 事件随 span 落轨迹。OTel bridge 在位时这些
        span/事件经既有 observer 投影到 OTel（不另接第二条导出通路）。
        """
        if not self._traceEnabled():
            return None, None
        try:
            from neurova.core.trace_recorder import get_trajectory_recorder

            recorder = get_trajectory_recorder()
            run.trace_id = recorder.start_trace(
                session_id=run.member_session_id,
                agent_id=run.agent_id,
                user_id=userId,
                metadata={
                    "kind": "swarm_member",
                    "subagent_id": run.subagent_id,
                    "parent_trace_id": run.parent_trace_id,
                    "parent_session_id": run.session_id or "",
                    "task": (run.task or "")[:200],
                    "depth": run.depth,
                },
            )
            if not run.trace_id:
                return None, None
            spanId = recorder.start_span(
                run.trace_id, "swarm_member_run", "swarm",
                parent_span_id=recorder.activeRootSpanId(run.trace_id),
            )
            recorder.record_event(
                run.trace_id, "info",
                {
                    "event": "subagent_started",
                    "subagent_id": run.subagent_id,
                    "agent_id": run.agent_id,
                    "model": run.model,
                    "origin": run.origin,
                    "depth": run.depth,
                },
                span_id=spanId,
            )
            return recorder, spanId
        except Exception as e:  # noqa: BLE001 - 轨迹故障不阻断子任务
            logger.debug("Swarm: member 轨迹开启失败（不阻断）: %s", e)
            return None, None

    def _endMemberTrace(self, recorder: Any, spanId: Optional[str], run: SubAgentRun) -> None:
        """收 span/轨迹：终态事件 + span 状态按 run 终态落，轨迹自动存档可查询。"""
        if recorder is None or not run.trace_id:
            return
        try:
            ok = run.status == SUBAGENT_COMPLETED
            if spanId:
                recorder.end_span(
                    spanId,
                    status="completed" if ok else "failed",
                    error_message=run.error or run.cause or None,
                )
            recorder.record_event(
                run.trace_id, "info",
                {
                    "event": "subagent_terminal",
                    "subagent_id": run.subagent_id,
                    "status": run.status,
                    "cause": run.cause,
                    "duration_ms": round(run.duration * 1000, 3),
                },
            )
            recorder.end_trace(run.trace_id)
        except Exception as e:  # noqa: BLE001 - 轨迹收尾故障不阻断子任务
            logger.debug("Swarm: member 轨迹收尾失败（不阻断）: %s", e)

    async def _run_member(
        self,
        run: SubAgentRun,
        agent: Any,
        initiator_agent: Optional[Any],
        stream: bool,
        subagentType: str = "general",
        toolAllowlist: Optional[frozenset] = None,
    ) -> None:
        """执行子 Agent 任务：广播 STARTED → chat（可流式）→ 广播 COMPLETED → 池归档"""
        run.status = SUBAGENT_RUNNING
        # P3-2（评测报告 G-12）：member 轨迹 trace——spawn→member→回流共一条可查询
        # 的 span 树；fail-open（轨迹故障/开关关闭不阻断子任务，与台账同口径）。
        userId = str(getattr(initiator_agent, "current_user_id", "")
                     or getattr(initiator_agent, "owner_user_id", "") or "")
        recorder, memberSpanId = self._startMemberTrace(run, userId)
        # 台账记账（§6-78 L 条）：写侧仍只在 `agent_run_ledger` 那一处，这里只调用。
        from neurova.core.agent_run_ledger import closeSubagentRun, openSubagentRun

        ledgerRunId = openSubagentRun(
            memberSessionId=run.member_session_id,
            subagentId=run.subagent_id,
            parentSessionId=run.session_id or "",
            userId=userId,
            agentId=run.agent_id,
            task=run.task,
            traceId=run.trace_id,
        )
        await self._broadcast(
            run,
            "subagent_started",
            {
                "subagent_id": run.subagent_id,
                "agent_id": run.agent_id,
                "agent_name": run.agent_name,
                "task": run.task,
                # 事件必须带事实：改前载荷没有 status，前端只能自己写死 'running'——
                # 那一刻后端确实是 running，但竞态/重放时前端无从校准，只能猜。
                "status": run.status,
                "origin": run.origin,
                "depth": run.depth,
                "subagent_type": run.subagent_type,
                "node_id": run.node_id,
                "execution_id": run.execution_id,
                "trace_id": run.trace_id,
                "parent_trace_id": run.parent_trace_id,
            },
        )

        # P2（工具清单 3.1-3 续）：失败交接的原料——content chunk 同步累积，
        # 失败/取消路径取尾部作部分报告（父代不再只拿到一句 error）。
        contentBuffer: List[str] = []
        emitter: Optional[StreamEmitter] = None
        if stream:
            emitter = self._make_emitter(run, contentBuffer)

        # 深度绑定：本条链的 member 在执行期读到 run.depth。member 内的
        # `spawn_subagent` 因此算出的 child_depth = run.depth + 1——深度沿链传递，
        # 与"同时有几个兄弟在跑"无关（切片 D：深度不是广度的副作用）。
        # 绑定必须在 `await agent.chat` 之前；`finally` 复位，避免污染同任务后续链。
        depth_token = set_subagent_depth(run.depth)
        # P1：绑定子代理工具面白名单（执行咽喉据此结构化拦截面外工具）
        from neurova.core.turn_context import set_subagent_tool_allowlist

        set_subagent_tool_allowlist(run.tool_allowlist)
        try:
            # [签名约束] Agent.chat(user_input, *, stream, save_memory, session_id,
            # metadata, enable_tts) —— 不接受 temperature/max_tokens，
            # 子 Agent 使用自身 llm_config（独立模型/人设是蜂群的前提）。
            # event_emitter 经 metadata 透传（chat_pipeline._init_agent_state 提取）
            # P2-9：session_id = member
            # 会话键——任务对话经既有 save_to_session 落盘到
            # sessions/<agent_id>/session_<member_session_id>_*.json，member
            # 拥有可查询/可审计/跨轮恢复的普通会话，完全复用单 agent 会话
            # 存储；不再用 None（不落盘、无历史）。member 内递归 spawn 时
            # 其 current_session_id 即 member 键，治理阀门天然覆盖递归。
            spawn_metadata = {
                "source": "swarm",
                "origin": run.origin,
                "subagent_id": run.subagent_id,
                "session_id": run.member_session_id,
            }
            if emitter is not None:
                spawn_metadata["event_emitter"] = emitter
            # stream=True（2026-09-10 蜂群超时排查）：非流式的读超时是"整段
            # 生成总窗口"，思考型子 agent 生成整份报告超窗即 ReadTimeout；
            # 流式按字节间隙计且静默看门狗/小窗实时流（SUBAGENT_CHUNK）全部依赖它
            #
            # K 条根修：流式把"整段总窗口"交给了调用方，而 `multi_model_client` 的
            # 静默看门狗**只留 WARNING 不中止**——上游停滞死流时这条 run 永久停在
            # running，既逐不出去也永远占着派生槽。故在此加一条与工具层同源的总闸。
            budget = self._effectiveRuntimeBudget()
            # P1-1：member 实际收到的是"原始任务描述 + 结构化任务书"拼装提示词；
            # 台账/事件里的 run.task 保持原始文本不混排。
            memberPrompt = renderTaskUnitPrompt(run.task, run.task_unit)

            async def doMemberChat(text: str) -> str:
                """一次 member 管线调用（流式/会话/预算与首跑同源），返回提取后正文。"""
                try:
                    response = await asyncio.wait_for(
                        agent.chat(
                            text,
                            stream=True,
                            session_id=run.member_session_id,
                            metadata=spawn_metadata,
                        ),
                        timeout=budget,
                    )
                except asyncio.TimeoutError:
                    run.cause = SUBAGENT_CAUSE_TIMEOUT
                    raise RuntimeError(
                        f"subagent_timeout（运行窗口 {budget:g}s 内未返回，已放弃这条子任务；"
                        f"尺度来自工具层 spawn_subagent 超时，可用 {SUBAGENT_BUDGET_ENV} 调整）"
                    ) from None
                textOut = self._extract_text(response)
                # P3：非流式遗留路径 LLM 失败不抛异常而是返回 "[LLM Error] ..." 文本
                # ——不得当正常报告标 completed（流式路径失败走异常分支天然 failed）
                if textOut.startswith("[LLM Error]"):
                    raise RuntimeError(textOut)
                return textOut

            report = await doMemberChat(memberPrompt)
            # P1-2（评测报告 G-3）验收门：判定 → 不达标带 missing 回炉一次 →
            # 再不达标置 failed（cause=acceptance_failed，产出不作合格结果回流）；
            # 判定器不可用诚实降级（completed + acceptance.skipped 标注）。
            verifyChannel = getattr(agent, "llm_client", None)
            gate = await runAcceptanceLoop(
                run,
                chatFn=doMemberChat,
                verifyChannel=getattr(verifyChannel, "chat", None),
                firstReport=report,
            )
            if gate.info is not None:
                run.acceptance = gate.info
            if gate.failedReason:
                run.cause = gate.cause
                raise RuntimeError(gate.failedReason)
            report = gate.report
            # P1-3（评测报告 G-5）监督评审相位：reviewMode=supervisor 时集成前评审；
            # 不通过带 findings 回炉一次，仍不通过置 failed（cause=review_failed）；
            # 评审器不可用诚实降级（completed + review.skipped 标注）。
            review = await runReviewLoop(
                run,
                chatFn=doMemberChat,
                verifyChannel=getattr(verifyChannel, "chat", None),
                firstReport=report,
            )
            if review.info is not None:
                run.review = review.info
            if review.failedReason:
                run.cause = review.cause
                raise RuntimeError(review.failedReason)
            report = review.report
            run.report = report
            run.status = SUBAGENT_COMPLETED
            run.finished_at = time.time()
        except asyncio.CancelledError:
            # 取消不是「没发生」：`CancelledError` 继承 `BaseException`，改前那一条
            # `except Exception` 抓不到它——run 就永久停在 running，槽位被占死（K 条）。
            # 现写终态、释放槽位，然后**照常上抛**：吞掉取消既是教义第 2 条的禁物，
            # 也会让 asyncio 的取消语义失真（外层以为没被取消）。
            run.status = SUBAGENT_FAILED
            run.cause = SUBAGENT_CAUSE_CANCELLED
            run.error = ("subagent_cancelled（父任务被取消，子任务未跑完；"
                         "派生槽已释放，可直接重派）")
            run.report = self._partialHandback(contentBuffer)
            run.finished_at = time.time()
            raise
        except Exception as e:  # noqa: BLE001 - 子 Agent 故障隔离
            logger.warning("Swarm: 子 Agent %s 执行失败: %s", run.subagent_id, e)
            run.status = SUBAGENT_FAILED
            run.error = str(e)
            run.report = self._partialHandback(contentBuffer)
            run.finished_at = time.time()
        finally:
            # 台账终态与蜂群终态同一个落点：`completed`/`failed`/超时/取消都从这里收尾，
            # 缺一条就在台账里留一行永久 running 的幽灵（L 条的另一副面孔）。
            closeSubagentRun(ledgerRunId, run.status, run.cause)
            self._endMemberTrace(recorder, memberSpanId, run)
            reset_subagent_depth(depth_token)
            set_subagent_tool_allowlist(None)

        await self._broadcast(
            run,
            "subagent_completed",
            {
                "subagent_id": run.subagent_id,
                "agent_id": run.agent_id,
                "agent_name": run.agent_name,
                "status": run.status,
                "report": run.report,
                "error": run.error,
                "depth": run.depth,
                "duration": run.duration,
                "node_id": run.node_id,
                "execution_id": run.execution_id,
                "trace_id": run.trace_id,
                "parent_trace_id": run.parent_trace_id,
            },
        )

        # 池归档通道：报告进入发起者上下文池，供后续语义召回
        self._archive_to_pool(initiator_agent, run)
        # 终态回灌通道：带正文投递发起者会话邮箱，供其 loop 下一轮排空
        self._notifyParentMail(run)

    @staticmethod
    def _extract_text(response: Any) -> str:
        """从 Agent.chat 返回值提取文本（dict{"text"} / str / 对象.content）"""
        if isinstance(response, dict):
            return str(response.get("text", ""))
        if hasattr(response, "content"):
            return str(response.content)
        return str(response) if response is not None else ""

    @staticmethod
    def _partialHandback(contentBuffer: List[str]) -> str:
        """失败交接（工具清单 3.1-3 续）：取失败前已流式产出的 content 尾部。

        父代拿到的失败 run 不再只有一句 error——已产出的部分分析随 report
        与终态邮箱一并上行，续跑（continue_subagent）时也是现成的上下文。
        截尾 4000 字符：交接件是给父代续判的抓手，不是全文存档（全文在
        member 会话里，信封带 recall 指针）。
        """
        partial = "".join(contentBuffer).strip()
        if not partial:
            return ""
        return partial[-4000:]

    def _make_emitter(
        self, run: SubAgentRun, contentBuffer: Optional[List[str]] = None
    ) -> StreamEmitter:
        """构造流式发射器：子 Agent 的 content/reasoning chunk → SUBAGENT_CHUNK 事件

        发射器由 ChatPipeline 在异步流式循环中同步调用，此处用 create_task
        调度广播（chunk 级 fire-and-forget 可接受，不阻塞生成循环）。

        P2（工具清单 3.1-3 续）：传入 contentBuffer 时同步累积 content chunk——
        失败交接用它取「失败前已产出的部分报告」；只认 content（reasoning 是
        思考过程，不是可交接的产出）。
        """

        _fire_refs: set = set()  # 批 X2：强引用集——事件循环对 Task 只持弱引用

        def _reap(task):
            _fire_refs.discard(task)

        def emitter(event_type: str, data: Any) -> None:
            # 卡死时钟的进度信号：chunk 到达 = member 活着（content 是产出，
            # reasoning 也是生命迹象——模型仍在工作）
            run.last_progress_at = time.monotonic()
            if contentBuffer is not None and event_type == "content" and isinstance(data, str):
                contentBuffer.append(data)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            task = loop.create_task(
                self._broadcast(
                    run,
                    "subagent_chunk",
                    {
                        "subagent_id": run.subagent_id,
                        "agent_name": run.agent_name,
                        "chunk_type": event_type,
                        "data": data,
                    },
                )
            )
            _fire_refs.add(task)
            task.add_done_callback(_reap)

        return emitter

    async def _broadcast(self, run: SubAgentRun, event_name: str, payload: Dict[str, Any]) -> None:
        """向聊天会话广播子 Agent 事件；无 session 或同步管理器不可用时静默跳过"""
        if not run.session_id:
            return
        try:
            from neurova.sync.session_sync_manager import (
                EventType,
                SessionEvent,
                get_session_sync_manager,
            )

            mgr = get_session_sync_manager()
            mgr.register_or_create_session(session_id=run.session_id, user_id="swarm")
            event = SessionEvent(
                event_type=EventType(event_name),
                session_id=run.session_id,
                source_channel="swarm",
                payload=payload,
            )
            await mgr.broadcast_event(run.session_id, event)
        except Exception as e:  # noqa: BLE001 - 广播失败不影响主流程
            logger.debug("Swarm: 事件广播失败 (%s): %s", event_name, e)

    def _archive_to_pool(self, initiator_agent: Optional[Any], run: SubAgentRun) -> None:
        """池归档通道：把终态信封归档进发起者的上下文池（活水，按需召回）"""
        if initiator_agent is None or run.status != SUBAGENT_COMPLETED or not run.report:
            return
        try:
            from neurova.context_pool import ContextInput, ContextSource

            pool = getattr(initiator_agent, "context_pool", None)
            if pool is None:
                return
            content = (
                "[子Agent报告] "
                + json.dumps(self._uplinkEnvelope(run), ensure_ascii=False)
            )
            pool.add_context(
                ContextInput(source=ContextSource.EXPERIENCE, content=content)
            )
            logger.info("Swarm: 子 Agent 终态信封已归档进发起者上下文池 (%s)", run.subagent_id)
        except Exception as e:  # noqa: BLE001 - 归档失败不影响返回
            logger.debug("Swarm: 报告归档失败: %s", e)

    def _uplinkEnvelope(self, run: SubAgentRun) -> Dict[str, Any]:
        """旁路上报的信封投影单源：关键信息 + 下钻指针，不含正文。

        正文有两个去处——主链路的 `to_dict()["report"]`（全文，同轮送达）与 member
        会话的 json（该子任务的全过程）。旁路再各抄一遍，就得为它发明长度尺度，
        那三处 `[:400]`/`[:2000]`/`[:300]` 的字面量正是这么长出来的。

        指针按 `agent_id` + `session_id` 二元组给：member 会话由写侧落在**子 Agent**
        的目录下，只带 session_id 的寻址会去主 Agent 的目录找一个不在那儿的地址。
        """
        return {
            "kind": "subagent_terminal",
            "subagent_id": run.subagent_id,
            "agent_id": run.agent_id,
            "agent_name": run.agent_name,
            "origin": run.origin,
            "depth": run.depth,
            "status": run.status,
            "cause": run.cause,
            "error": run.error,
            "duration": run.duration,
            "model": run.model,
            "node_id": run.node_id,
            "execution_id": run.execution_id,
            "trace_id": run.trace_id,
            "parent_trace_id": run.parent_trace_id,
            "transcript": {
                "agent_id": run.agent_id,
                "session_id": run.member_session_id,
                "recall": (
                    f"recall_history(agent_id={run.agent_id}, "
                    f"session_id={run.member_session_id})"
                ),
            },
        }

    def _notifyParentMail(self, run: SubAgentRun) -> None:
        """终态回灌通道：把终态信封投递发起者会话的邮箱。

        投递点是**终态**而不是 `spawn()` 的返回处——后台派生返回那一刻子任务还没
        跑完，绑在返回处投不出终态；而报告在信封里只有一个键名 `report`
        （见 `SubAgentRun.to_dict()`），在下游猜键名正是本处取代的旧形态。
        失败/超时/取消同样投：终态沉默会让主 Agent 以为子任务还在跑。

        只认 chat 来源——workflow 派生的报告交给引擎的 `output`，它的 `session_id`
        只是事件广播目标，投进邮箱无人排空。
        """
        self.pushParentMail(run, "子Agent终态", self._uplinkEnvelope(run))


    def getRunByMemberSession(self, memberSessionId: str) -> Optional[SubAgentRun]:
        """按 member 会话找**活跃**的子代理运行（子代理回合内的工具调用，
        其 turn session 即 member_session_id）；无则 None。"""
        if not memberSessionId:
            return None
        for run in self._runs.values():
            if (
                run.member_session_id == memberSessionId
                and run.status in SUBAGENT_ACTIVE_STATUSES
            ):
                return run
        return None

    def pushParentMail(self, run: SubAgentRun, tag: str, envelope: Dict[str, Any]) -> bool:
        """父会话邮箱投递的**唯一写点**（邮箱写点单源钉子：生产面只许 swarm.py 一处写）。

        终态回灌/卡死提醒/升级/结果提交/审批信封（P3-1）都经这里投递；
        仅 chat 来源且有会话才投；失败不影响调用方主流程（诚实 debug，不吞成无声）。
        """
        if run.origin != "chat" or not run.session_id:
            return False
        try:
            from neurova.agent.mailbox import get_agent_mailbox

            get_agent_mailbox().push(
                run.session_id,
                f"[{tag}] " + json.dumps(envelope, ensure_ascii=False),
            )
            return True
        except Exception as e:  # noqa: BLE001 - 投递失败不影响主流程
            logger.debug("Swarm: 父会话邮箱投递失败 (%s): %s", run.subagent_id, e)
            return False

    def recordEscalation(
        self, run: SubAgentRun, reason: str, question: str = "", severity: str = "normal",
        suggestedAction: str = "", actionNote: str = "",
    ) -> Dict[str, Any]:
        """记录子代理升级，并把升级信封投递发起者会话邮箱（主代理/用户可见）。

        P2-5（评测报告 G-8）：升级带建议处置动作（clarify/reassign/revise_dependency/
        retry），主代理据此走结构化闭环而不是自由发挥。
        """
        run.escalation = {
            "reason": str(reason or ""),
            "question": str(question or ""),
            "severity": str(severity or "normal"),
            "suggested_action": str(suggestedAction or ""),
            "action_note": str(actionNote or ""),
            "at": time.time(),
        }
        envelope = {
            "kind": "escalate",
            "subagent_id": run.subagent_id,
            "agent_id": run.agent_id,
            "agent_name": run.agent_name,
            "task": run.task,
            "reason": run.escalation["reason"],
            "question": run.escalation["question"],
            "severity": run.escalation["severity"],
            "suggested_action": run.escalation["suggested_action"],
            "action_note": run.escalation["action_note"],
        }
        self.pushParentMail(run, "子Agent升级", envelope)
        return envelope

    def recordSubmittedResult(
        self, run: SubAgentRun, summary: str, status: str = "success"
    ) -> Dict[str, Any]:
        """记录子代理的结构化结果提交，并投递发起者会话邮箱。"""
        run.submitted_result = {
            "summary": str(summary or ""),
            "status": str(status or "success"),
            "at": time.time(),
        }
        if str(summary or "").strip():
            run.report = str(summary)
        envelope = {
            "kind": "submit_result",
            "subagent_id": run.subagent_id,
            "agent_id": run.agent_id,
            "agent_name": run.agent_name,
            "task": run.task,
            "summary": run.submitted_result["summary"],
            "status": run.submitted_result["status"],
        }
        self.pushParentMail(run, "子Agent结果", envelope)
        return envelope


# ── 单例生命周期 ────────────────────────────────────────────────

_swarm_manager_instance: Optional[SwarmManager] = None


@lazySingleton("_swarm_manager_instance")
def get_swarm_manager() -> SwarmManager:
    return SwarmManager()


def reset_swarm_manager() -> None:
    global _swarm_manager_instance
    _swarm_manager_instance = None


__all__ = [
    "SubAgentRun",
    "SwarmManager",
    "current_subagent_depth",
    "get_swarm_manager",
    "reset_subagent_depth",
    "reset_swarm_manager",
    "set_subagent_depth",
]
