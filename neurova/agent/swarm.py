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
from typing import Any, Callable, Dict, List, Optional
from neurova.agent.task_unit import parseTaskUnit, renderTaskUnitPrompt
from neurova.agent.acceptance_gate import runAcceptanceLoop
from neurova.agent.review_gate import runReviewLoop
from neurova.agent.candidate_merge import CandidateMergeBoard
from neurova.agent.context_firewall import buildDataFence
from neurova.core.lazy_singleton import lazySingleton
from neurova.core.trace_context import get_trace_id
# run 生命周期支撑（状态词汇/SubAgentRun/迁移状态机/谱系/启动收敛）已纯移动至
# swarm_support；此处再导出，保持既有调用方与 monkeypatch 点（neurova.agent.swarm.*）不变。
from neurova.agent.swarm_support import (
    RUN_STATUS_TRANSITIONS,
    SUBAGENT_ACTIVE_STATUSES,
    SUBAGENT_COMPLETED,
    SUBAGENT_FAILED,
    SUBAGENT_FINISHED_STATUSES,
    SUBAGENT_IN_REVIEW,
    SUBAGENT_PENDING,
    SUBAGENT_RUNNING,
    SUBAGENT_STATUSES,
    IllegalRunStatusTransition,
    SubAgentRun,
    buildRunLineage,
    reconcileSwarmRunsAtStartup,
    replayRunTailStatus,
    requiresReviewConfirmation,
    transitionRun,
)

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


# F5 谱系：当前正在执行的 member 的 run id（顶层会话 = 空串）。member 内
# 递归派生时，子代 spawn 路径（spawn_subagent 工具 → SwarmManager.spawn）
# 在构造 run 时读它作为 parent_subagent_id——父链只在 spawn 时刻读一次。
# 与 _subagentDepthVar 同形态同生命周期：挂 Agent 实例会在并发链间互踩；
# `_run_member` 在子 Agent chat 之前按 run.subagent_id 绑定、finally 复位。
_currentSubagentIdVar: ContextVar = ContextVar("neurova_current_subagent_id", default="")


def currentSubagentId() -> str:
    """当前执行上下文对应的 member run id（顶层会话 = 空串）。"""
    return str(_currentSubagentIdVar.get() or "")


def setCurrentSubagentId(subagent_id: str):
    """绑定当前执行的 member run id，返回 token 供复位。"""
    return _currentSubagentIdVar.set(str(subagent_id or ""))


def resetCurrentSubagentId(token) -> None:
    """复位 member run id 到绑定前（token 由 setCurrentSubagentId 返回）。"""
    _currentSubagentIdVar.reset(token)


#: 运行窗口预算的覆盖入口；**默认值不写在蜂群里**，取 `tool_coordinator` 的
#: `spawn_subagent` 那份读数（同一件事只许有一个尺度，见 `_effectiveRuntimeBudget`）
SUBAGENT_BUDGET_ENV = "NEUROVA_SWARM_SUBAGENT_BUDGET_SEC"

#: 子代理（swarm member）会话上下文软目标（token 估算）：member 会话估算 token
#: 越过该线即**先于硬预算**（模型窗口×触发水位）触发压缩，防止 member 长任务把
#: 上下文顶到模型上限。与 S6 压缩机制合流（同一触发/守卫/事件面，不新造第二套）；
#: 识别单源是 turn_origin.resolve_turn_origin（metadata source=swarm 既有约定）。
SUBAGENT_CONTEXT_SOFT_TARGET_TOKENS = 20000

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

#: S4 结果候选制的合入审批分级（L0 自动放行留痕 / L1 提示 / L2 必审）。
#: 合入是可逆记账动作（候选正文始终保留在板上），默认 L0；运维可调高。
MERGE_APPROVAL_LEVEL_ENV = "NEUROVA_SWARM_MERGE_APPROVAL_LEVEL"

# S9 动态组队：团队成员职责 prompt 拼进任务书角色段时的上限（具名常量——
# "正文不得按字面量砍长度"常驻钉子；超限职责由 TASK_TOO_LARGE 硬限诚实拒绝）
TEAM_DUTY_PROMPT_MAX_CHARS = 2000
# 收尾成因的常量由台账侧持有（`agent_run_ledger`），swarm 只引用不自造第二份：
# 台账的 error_type 与这里的 cause 必须是同一批词值。
from neurova.core.agent_run_ledger import (
    SUBAGENT_CAUSE_CANCELLED, SUBAGENT_CAUSE_TIMEOUT,
)

# H-4 事件账本里 task/error 的摘要上界（具名声明——正文长度尺度不许散落数字上界）
EVENT_TASK_SUMMARY_CHARS = 80
EVENT_ERROR_SUMMARY_CHARS = 160


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


#: 成员工具面剔除集收口于 builtin_tools.MAIN_AGENT_ONLY_TOOLS（单一事实源，
#: 教义第 6 条；S13 移交项①并集收口）——白名单派生与执行咽喉成员门读同一份声明。


def computeSubagentToolAllowlist(
    subagentType: str, borrowMcp: frozenset = frozenset()
) -> frozenset:
    """按子代理类型计算工具面白名单（P1 蜂群对照；spawn 与测试共用的单一出口）。

    - general：全量内置工具 − 成员剔除集（见 ``MAIN_AGENT_ONLY_TOOLS``）；
      可选借用父上下文的 MCP 调用面（``borrowMcp`` 快照，P3 #8）；
    - explore：只读白名单 − 成员剔除集（检索/侦察型子代理不拿写工具，也不借 MCP）。
    执行咽喉（ToolExecutor._execute_single_tool）据 member 上下文绑定的
    白名单强制拦截面外工具。
    """
    from neurova.builtin_tools import (
        MAIN_AGENT_ONLY_TOOLS,
        get_builtin_tool_capability,
        get_registered_tool_names,
    )

    if str(subagentType or "").strip().lower() == "explore":
        readonlyNames = []
        for toolName in get_registered_tool_names():
            cap = get_builtin_tool_capability(toolName)
            if cap is not None and getattr(cap, "readOnly", False):
                readonlyNames.append(toolName)
        return frozenset(readonlyNames) - MAIN_AGENT_ONLY_TOOLS
    # 前台输入注入族（P2-4 电脑操控对照）：对齐「CUA 仅主代理」——多代理并发抢
    # 真实鼠标/键盘 = 互踩用户桌面；观察面与 shell/ssh 保留。
    from neurova.computer_use import foregroundDesktopTools

    return (frozenset(get_registered_tool_names()) - MAIN_AGENT_ONLY_TOOLS
            - foregroundDesktopTools()) | frozenset(borrowMcp)


def memberChatScope(run: Any) -> str:
    """蜂群 member 轮的记忆作用域标签（S9 要点4 共享黑板）。

    run 关联协作房间时复用 ``room:<room_id>`` 作用域语义（不新造作用域体系）：
    同房间内跨成员共享、群群隔离、读单聊基线，全部继承 room 既有语义。
    返回空串 = 无房间关联，走缺省 direct。
    """
    roomId = str(getattr(run, "room_id", "") or "").strip()
    return f"room:{roomId}" if roomId else ""


def composeTeamDutyTask(task: str, member: Any) -> str:
    """团队成员职责 prompt 拼进任务书角色段（S9/S10 唯一拼装形态）。

    职责来自团队名册（用户资产），进任务书前受 ``TEAM_DUTY_PROMPT_MAX_CHARS``
    约束（"正文不得按字面量砍长度"钉子：上限是具名常量）。无职责时原样返回。
    """
    duty = str((member or {}).get("prompt") or "").strip()
    if not duty:
        return task
    roleLabel = str((member or {}).get("role") or "participant")
    return f"[团队职责 · {roleLabel}] {duty[:TEAM_DUTY_PROMPT_MAX_CHARS]}\n\n{task}"


def _settingsDefaultSubagentDepth() -> int:
    """深度上限的默认值：**取自** `agent_limits_settings.DEFAULTS` 单源。

    本函数只是把单源的值搬进类属性（供设置不可读时的 `_effective_max_depth()`
    回落），不在此手抄第二份数字。单源不可导入是真实故障，交给 import 出声，
    不吞异常改成静默常量。
    """
    from neurova.security.agent_limits_settings import DEFAULTS

    return int(DEFAULTS["max_subagent_depth"])


# ── A3 命令回执（参照系 ac 借鉴）：连接装配 ─────────────────────────────

_RECEIPT_CONN = None
_RECEIPT_CONN_LOCK = threading.RLock()


def _receiptConnection():
    """命令回执库连接（按数据根派生单文件；command_receipt 独立版本域）。

    与 mobile_ws_ledger 同范式：每域一库，user_version 互不干扰。
    """
    global _RECEIPT_CONN
    if _RECEIPT_CONN is not None:
        return _RECEIPT_CONN
    with _RECEIPT_CONN_LOCK:
        if _RECEIPT_CONN is None:
            import sqlite3

            from neurova.core.command_receipt import ensureReceiptStore
            from neurova.core.data_root import get_data_root

            path = get_data_root() / "command_receipt.db"
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), check_same_thread=False)
            ensureReceiptStore(conn)
            _RECEIPT_CONN = conn
    return _RECEIPT_CONN


def _receiptRejection(exc: Exception) -> Dict[str, Any]:
    """回执类错误 → 蜂群统一拒绝结构（诚实点名原因，不吞不改写）。"""
    from neurova.core.command_receipt import (
        CommandIdConflictError,
        PreviouslyRejectedError,
    )

    reason = "COMMAND_IN_FLIGHT"
    if isinstance(exc, CommandIdConflictError):
        reason = "COMMAND_ID_CONFLICT"
    elif isinstance(exc, PreviouslyRejectedError):
        reason = "COMMAND_PREVIOUSLY_REJECTED"
    return {
        "rejected": True,
        "rejection": reason,
        "success": False,
        "error": f"[{reason}] {exc}",
    }


def _handoffTokenCap() -> int:
    """续跑交接的 token 预算上限（B2）：环境变量可覆盖，缺省取工件模块单源。

    非法值回落缺省；夹取（[1024, 64000]）由 buildHandoff 内的 clampTokenCap 兜住。
    """
    raw = (os.environ.get("NEUROVA_CONTEXT_HANDOFF_TOKEN_CAP") or "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            logger.warning("NEUROVA_CONTEXT_HANDOFF_TOKEN_CAP=%r 不是整数，回落缺省", raw)
    from neurova.agent.context_transfer import DEFAULT_TOKEN_CAP

    return DEFAULT_TOKEN_CAP


# ── A2 全局事件库（参照系 ac 借鉴）：H-4 账本双写镜像 ────────────────────

_EVENT_STORE = None
_EVENT_STORE_LOCK = threading.RLock()


def _eventStore():
    """全局事件库连接（惰性单例；库文件落 swarm_runs 目录下专用文件）。

    双写纪律：JSONL 账本仍是 H-4 一手事实源，本库是全局序镜像（重放/快照
    协议用）；镜像 fail-open，绝不阻断蜂群主流程。
    """
    global _EVENT_STORE
    if _EVENT_STORE is not None:
        return _EVENT_STORE
    with _EVENT_STORE_LOCK:
        if _EVENT_STORE is None:
            from pathlib import Path

            from neurova.agent.swarm_event_store import SwarmEventStore
            from neurova.core.data_root import dataPath

            store = SwarmEventStore(str(Path(dataPath("swarm_runs")) / "event_store.db"))
            _EVENT_STORE = store
    return _EVENT_STORE


def _deliveryLedger():
    """子代理完成投递账本（B1）：投递单 pending→claimed→acknowledged|disposed
    的状态机与父闲补投，接在 pushParentMail 唯一写点与邮箱消费侧 ack 镜像。
    单例单源在 delegated_delivery.getDeliveryLedger，此处委托（历史调用点不变）。"""
    from neurova.agent.delegated_delivery import getDeliveryLedger

    return getDeliveryLedger()


def _mailOutbox():
    """effect outbox（A3）：崩溃安全的投递**意图层**（SQLite 持久）。

    与 _deliveryLedger 同范式委托：单例单源在 mail_outbox.getMailOutbox。
    分工——账本记投递的活体状态（进程内），outbox 记投递意图（跨崩溃），
    邮箱 messageId 幂等是重投去重的安全网。
    """
    from neurova.agent.mail_outbox import getMailOutbox

    return getMailOutbox()


def redeliverOutboxIntent(intent: Dict[str, Any]) -> bool:
    """outbox 启动对账的投递函数（swarm.py 是邮箱投递唯一写点，重投也落此）。

    正文/优先级/messageId 均取自登记时的 payload——messageId 不变，邮箱按
    messageId 幂等去重，崩溃前已入箱的消息重投只补销账、不重复生效
    （宁重不丢）。
    """
    from neurova.agent.mailbox import get_agent_mailbox

    payload = intent.get("payload") or {}
    envelope = payload.get("envelope")
    if envelope is None:
        envelope = {}
    return get_agent_mailbox().push(
        str(payload.get("session_id") or ""),
        f"[{payload.get('tag') or '子Agent结果'}] "
        + json.dumps(envelope, ensure_ascii=False),
        priority=str(payload.get("priority") or "normal"),
        message_id=str(payload.get("message_id") or intent.get("intent_id") or ""),
    )


_RUN_QUEUE = None
_RUN_QUEUE_LOCK = threading.RLock()


def _runQueue():
    """排队 run 管理面（B4，惰性单例）：队列位次/优先级/取消/任务书修订。"""
    global _RUN_QUEUE
    if _RUN_QUEUE is not None:
        return _RUN_QUEUE
    with _RUN_QUEUE_LOCK:
        if _RUN_QUEUE is None:
            from neurova.agent.run_queue import RunQueue

            _RUN_QUEUE = RunQueue()
    return _RUN_QUEUE


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
        # S4 结果候选板：member 结果先落候选（submitted），主侧 CAS 合入；
        # 冲突保留升级。随管理器单例存活，留痕经 H-4 run 事件账本。
        self._candidates = CandidateMergeBoard()
        # B3：外部编码代理成员的适配器登记（subagent_id → (adapter, spawnLoop)）。
        # cancelRun 据此把叫停传导进外部代理进程（adapter.cancel → executor.cancel
        # → ACP session/cancel）；run 到终态即摘除。spawnLoop 是派生时的事件循环，
        # 供无循环的调用线程经 run_coroutine_threadsafe 投递取消协程。
        self._externalAdapters: Dict[str, tuple] = {}
        # P1 移交清偿：run 终态后释放外部适配器的后台任务强引用集（防 GC 吞任务）。
        self._adapterCloseTasks: set = set()
        self._lock = threading.RLock()
        # A5 终态助推账本：_nextSweepDue=下次助推扫掠到期时刻（epoch 秒，0=无待跑）；
        # _settleBoostJobRegistered 防重复注册 60s 轻量 job（开关开才注册）。
        self._nextSweepDue = 0.0
        self._settleBoostJobRegistered = False
        # A5：自动结算开启时才挂定时 sweep（默认关——不拉起调度器，测试零污染）。
        # 每小时一轮；管理面也可直接调 settleIdleRuns() 手动触发。
        try:
            from neurova.agent.run_settlement import readSettleSettings

            if readSettleSettings()[0]:
                from neurova.agent.scheduler import get_scheduler

                get_scheduler().addSystemJob(
                    self.settleIdleRuns, "swarm_run_settlement_sweep", 3600)
        except Exception as initError:  # noqa: BLE001 - 注册失败不阻断编排
            logger.debug("Swarm: 结算 job 注册失败: %s", initError)

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
        room_id: Optional[str] = None,
        project_id: Optional[str] = None,
        team_id: Optional[str] = None,
        team_role: Optional[str] = None,
        teamMemberOverride: Optional[dict] = None,
        runtimeBudgetSec: Optional[float] = None,
    ) -> Dict[str, Any]:
        """派生子 Agent 执行任务

        Args:
            task: 交给子 Agent 的完整任务描述
            agent_id: 目标子 Agent ID；None 用 default；不存在回退 default
            session_id: 聊天会话 ID（事件广播目标；None 则不广播）
            background: True 后台执行（立即返回 subagent_id）
            origin: 来源（chat | workflow | team_dispatch | room_collab），用于事件追踪
            stream: True 时子 Agent 的 content/reasoning 逐 chunk 广播
            initiator_agent: 发起者 Agent 实例（用于结果归档进其上下文池）
            node_id / execution_id: workflow 来源时的定位信息
            reuse_member_session_id: 复用既有 member 会话键（续跑用——子 Agent
                的历史由既有会话恢复机制带回）；None 新建
            resumed_from: 被续跑的 subagent_id（溯源读数；空 = 全新派生）
            room_id: S9 关联协作房间（=协作 project_id）——审批/升级/候选事件投递
                到该房间（人在环闭环），member 记忆按 room:<room_id> 作用域共享
            project_id: S12 run→project 归属标（落台账 project_id 列，项目档案按
                此聚合）；缺省取 room_id（房间发起的协作按等式自动打标），显式
                传入时优先——主 agent 直发带项目上下文走这一入口
            team_id / team_role: S9 动态组队——按团队名册选人（team_role 复用
                collaboration_template.AgentRole），成员职责 prompt 拼进任务书
            teamMemberOverride: S10 dispatch_team 显式点名成员（跳过按角色/任务
                文本的自动选人——同名角色多名成员时自动选人会歧义）
            runtimeBudgetSec: S10/S11 本 run 的运行窗口覆盖（秒）；None/0 用治理面默认

        Returns:
            前台: {subagent_id, agent_id, agent_name, status, report, duration, ...}
            后台: {subagent_id, agent_id, agent_name, status: "pending", background: True}
        """
        if not task or not str(task).strip():
            return {"error": "task 不能为空"}

        # S9 动态组队：按团队名册选人；选中成员的职责 prompt 拼进任务书角色段
        #（长度校验在拼装之后统一做，职责段一并受 MAX_TASK_CHARS 管辖）。
        # S10：dispatch_team 显式点名成员时跳过自动选人（override 来自名册本身，
        # 职责段已由 dispatchTeam 经 composeTeamDutyTask 拼好，此处不重复注入）。
        if teamMemberOverride is not None:
            teamMember, teamRejection = dict(teamMemberOverride), None
        else:
            teamMember, teamRejection = self._resolveTeamMember(team_id, team_role, str(task))
            if teamRejection is not None:
                return teamRejection
        teamRoleLabel = ""
        if teamMember:
            teamRoleLabel = str(teamMember.get("role") or team_role or "")
            if teamMemberOverride is None:
                task = composeTeamDutyTask(task, teamMember)

        # S12 run→project 归属标：显式 project_id 优先（入口一直发带项目上下文），
        # 否则按 ``room_id = 协作 project_id`` 等式取房间标（入口二房间发起）。
        effectiveProjectId = str(project_id or "").strip() or str(room_id or "").strip()

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
        # F5 谱系：member 内递归派生时，当前上下文绑定的就是父 member 的 run id
        #（_run_member 在 chat 前绑定）；顶层派生此处读到空串。spawn 时刻读一次。
        parentSubagentId = currentSubagentId()
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

        # 外部编码代理（名册 executor 成员）：显式 agent_id 点名优先，
        # 其次团队自动选人命中的成员；两处都未命中 executor 才走内置解析。
        externalAdapter, externalError, externalId = None, None, ""
        for externalCandidate in (agent_id, str((teamMember or {}).get("user_id") or "")):
            if not externalCandidate:
                continue
            externalAdapter, externalError = self._resolveExternalMember(externalCandidate, team_id)
            if externalAdapter is not None or externalError:
                externalId = externalCandidate
                break
        if externalError:
            return self._rejection("EXTERNAL_AGENT_UNAVAILABLE", externalError)
        if externalAdapter is not None:
            # chat 兼容适配器直接作为 member 执行体（设计文档 §4.2）
            agent, resolved_id, fallback = externalAdapter, externalId, False
        else:
            agent, resolved_id, fallback = self._resolve_agent(agent_id)
        if agent is None:
            return {"error": f"未找到可用的子 Agent（请求: {agent_id or 'default'}）"}

        model = self._resolve_model_name(agent)
        # D-B：外部成员在 spawn 时刻冻结执行体档案（能力档/工具标识/模型名）
        # ——续跑时与名册现值比较得出切换决策，名册中途改动不再被无感吞掉。
        executorProfile = (
            self._executorProfileFor(externalId, team_id)
            if externalAdapter is not None else None
        )
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
                        "room_id": str(room_id or "").strip(),
                        "project_id": effectiveProjectId,
                        # D-B：外部成员（即使未走团队选人）也保留名册归属——
                        # 续跑/切换按名册现值决策与租户判定都要用它。
                        "team_id": str(team_id or "").strip()
                        if (teamMember or externalAdapter is not None) else "",
                        "team_role": teamRoleLabel,
                        "team_member": dict(teamMember) if teamMember else None,
                        "runtime_budget_sec": max(0.0, float(runtimeBudgetSec or 0.0)),
                        # F5 谱系：父链在 spawn（登记等待）时刻固定，放行时不重读
                        "parent_subagent_id": parentSubagentId,
                        # B3：外部成员适配器随等待件携带——放行时直接续用，
                        # 不再走 _resolve_agent（外部 id 不在 Agent 注册表里）。
                        "external_adapter": externalAdapter,
                        "deps": list(deps), "status": "blocked", "created_at": time.time(),
                    }
                # 依赖门 return 必须在 if unsatisfied: 之内——全部依赖已满足时
                # blockedId 未定义，落到这里就是 UnboundLocalError（根修：只有
                # 真有未满足依赖才走 blocked 登记，否则落到下方正常派生）。
                return {
                    "subagent_id": blockedId, "agent_id": resolved_id,
                    "status": "blocked", "background": True,
                    "dependencies": list(deps), "unsatisfied": unsatisfied,
                    "data_fence": dataFence,
                    "room_id": str(room_id or "").strip(),
                    "project_id": effectiveProjectId,
                    "team_id": str(team_id or "").strip() if teamMember else "",
                    "team_role": teamRoleLabel,
                    "selected_member": teamMember,
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
            room_id=str(room_id or "").strip(),
            project_id=effectiveProjectId,
            # D-B：外部成员（即使未走团队选人）也保留名册归属——续跑/切换的
            # 决策与租户判定都要用它。
            team_id=str(team_id or "").strip()
            if (teamMember or externalAdapter is not None) else "",
            team_role=teamRoleLabel,
            team_member=dict(teamMember) if teamMember else None,
            runtime_budget_sec=max(0.0, float(runtimeBudgetSec or 0.0)),
            # D-B：spawn 时刻执行体档案快照（外部成员专有；本仓 agent 为 None/""）
            executor_caps_snapshot=dict(executorProfile["caps"]) if executorProfile else None,
            executor_tool=executorProfile["tool"] if executorProfile else "",
            executor_model=model or "",
            # F5 谱系：spawn 时刻单源（租户/父链只在此读一次）
            tenant_id=self._currentTenantId(),
            parent_subagent_id=parentSubagentId,
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
            # B3：外部成员适配器随 run 登记（终态在 _execute finally 摘除），
            # cancelRun 据此向外部代理进程传导叫停。
            if externalAdapter is not None:
                self._externalAdapters[run.subagent_id] = (
                    externalAdapter, asyncio.get_running_loop())
            self._evict_finished_runs()

        # H-4：派生事实入 run 事件账本（正文不进账本，task 只留摘要）
        self._logRunEvent(run, "spawned", {
            "task": run.task[:EVENT_TASK_SUMMARY_CHARS], "origin": run.origin, "depth": run.depth,
            "subagent_type": run.subagent_type, "model": run.model,
            "parent_trace_id": run.parent_trace_id,
        })
        # B4：与 spawned 事件同点入排队管理面（位次/优先级/修订/取消的读改单源）
        self._registerRunQueue(run)

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
                "room_id": run.room_id,
                "project_id": run.project_id,
                "team_id": run.team_id,
                "team_role": run.team_role,
                "selected_member": teamMember,
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

    # ── S10：固定团队整体派活（多路 spawn 的编排糖，治理三明治照走）────────

    async def dispatchTeam(
        self,
        teamId: str,
        task: str,
        taskUnit: Optional[dict] = None,
        session_id: Optional[str] = None,
        initiator_agent: Optional[Any] = None,
        background: bool = True,
        subagentType: str = "general",
        runtimeBudgetSec: Optional[float] = None,
        command_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """把固定团队整体派活（A3 回执幂等包装）。

        ``command_id`` 非空时整段派活走命令回执：同 ID 重试按回执重放结果、
        不重复 spawn；跨会话复用同 ID 报 COMMAND_ID_CONFLICT；曾拒绝的 ID
        不可重试（COMMAND_PREVIOUSLY_REJECTED）。空（缺省）保持原行为。
        """
        cid = str(command_id or "").strip()
        if not cid:
            return await self._dispatchTeamInner(
                teamId, task, taskUnit=taskUnit, session_id=session_id,
                initiator_agent=initiator_agent, background=background,
                subagentType=subagentType, runtimeBudgetSec=runtimeBudgetSec,
            )
        from neurova.core.command_receipt import executeWithReceiptAsync

        async def _afn() -> Dict[str, Any]:
            return await self._dispatchTeamInner(
                teamId, task, taskUnit=taskUnit, session_id=session_id,
                initiator_agent=initiator_agent, background=background,
                subagentType=subagentType, runtimeBudgetSec=runtimeBudgetSec,
            )

        try:
            result, replayed = await executeWithReceiptAsync(
                _receiptConnection(),
                command_id=cid,
                command_type="dispatch_team",
                thread_id=str(session_id or teamId or ""),
                afn=_afn,
            )
        except Exception as exc:  # noqa: BLE001 - 回执三态错误如实转拒绝结构
            return _receiptRejection(exc)
        if replayed:
            result = dict(result or {})
            result["replayed"] = True
        return result

    async def _dispatchTeamInner(
        self,
        teamId: str,
        task: str,
        *,
        taskUnit: Optional[dict] = None,
        session_id: Optional[str] = None,
        initiator_agent: Optional[Any] = None,
        background: bool = True,
        subagentType: str = "general",
        runtimeBudgetSec: Optional[float] = None,
    ) -> Dict[str, Any]:
        """把固定团队整体派活：按名册生成多路 spawn（每成员一路）。

        - 成员职责 prompt 注入任务书角色段（复用 spawn 的 teamMember 注入形态）；
        - taskUnit.dependencies 做**步间编排**：依赖项按名册序号（"0"/"1"…）或
          成员 user_id/显示名声明，派生时映射为该成员的 subagent_id——只允许
          指向名册中更早的成员（后向引用在 spawn 的依赖门处诚实拒绝）；
        - 每一路都走完整 spawn 治理三明治（深度/广度/预算/冷却/并发/错峰照算，
          不绕过）；run 带 teamId 溯源标（origin="team_dispatch"）；
        - 验收门/评审相位/候选制照走（spawn 主链路原样）。
        """
        tid = str(teamId or "").strip()
        if not tid:
            return self._rejection("TEAM_ID_REQUIRED", "dispatch_team 需要 teamId（要派活的固定团队）")
        if not task or not str(task).strip():
            return {"error": "task 不能为空"}
        from neurova.api.endpoints.teams_api import getTeamRoster

        roster = getTeamRoster(tid)
        if roster is None:
            return self._rejection("TEAM_UNKNOWN", f"团队不存在: {tid}")
        members = [m for m in (roster.get("members_detail") or [])
                   if str(m.get("user_id") or "").strip()]
        if not members:
            return self._rejection("TEAM_EMPTY", f"团队 {tid} 名册为空——请先添加团队成员")

        try:
            parsedUnit = parseTaskUnit(taskUnit)
        except ValueError as exc:
            return self._rejection("TASK_UNIT_INVALID", f"task_unit 非法：{exc}")

        # 依赖引用解析表：名册序号 / user_id / 显示名 → 成员位次
        indexByKey: Dict[str, int] = {}
        for idx, member in enumerate(members):
            indexByKey[str(idx)] = idx
            indexByKey.setdefault(str(member.get("user_id") or ""), idx)
            memberName = str(member.get("name") or "")
            if memberName:
                indexByKey.setdefault(memberName, idx)

        dispatches: List[Dict[str, Any]] = []
        spawnedIds: Dict[int, str] = {}
        for idx, member in enumerate(members):
            memberTask = composeTeamDutyTask(str(task), member)
            memberUnit: Optional[Dict[str, Any]] = None
            droppedDeps: List[str] = []
            if parsedUnit is not None:
                unitDict = parsedUnit.toDict()
                remapped: List[str] = []
                for dep in unitDict.get("dependencies") or []:
                    depKey = str(dep or "").strip()
                    targetIdx = indexByKey.get(depKey)
                    if targetIdx is None:
                        # 名册外引用原样保留（外部 subagent_id，交给依赖门判定）
                        remapped.append(depKey)
                    elif targetIdx < idx and targetIdx in spawnedIds:
                        # 名册内更早成员 → 已派生的 subagent_id（依赖门按 run 编排）
                        remapped.append(spawnedIds[targetIdx])
                    else:
                        # 自引用/名册内后向引用：本批派生按名册序进行，该依赖在本批内
                        # 不可满足（等自己/等还没派生的兄弟 = 永久 blocked）——如实丢弃
                        droppedDeps.append(depKey)
                unitDict["dependencies"] = remapped
                memberUnit = unitDict
            result = await self.spawn(
                task=memberTask,
                agent_id=str(member.get("user_id") or "").strip(),
                session_id=session_id,
                background=background,
                origin="team_dispatch",
                stream=True,
                initiator_agent=initiator_agent,
                subagent_type=subagentType,
                task_unit=memberUnit,
                team_id=tid,
                team_role=str(member.get("role") or "") or None,
                teamMemberOverride=dict(member),
                runtimeBudgetSec=runtimeBudgetSec,
            )
            spawnedIds[idx] = str(result.get("subagent_id") or "")
            entry = {
                "member": dict(member),
                "subagent_id": result.get("subagent_id"),
                "status": result.get("status"),
                "rejected": bool(result.get("rejected")),
                "rejection": result.get("rejection"),
                "error": result.get("error"),
            }
            if droppedDeps:
                entry["dropped_dependencies"] = droppedDeps
            dispatches.append(entry)
        failed = [d for d in dispatches if d["rejected"] or d.get("error")]
        return {
            "success": True,
            "team_id": tid,
            "team_name": roster.get("name", ""),
            "origin": "team_dispatch",
            "dispatches": dispatches,
            "subagent_ids": [d["subagent_id"] for d in dispatches if d["subagent_id"]],
            "failed_count": len(failed),
            "background": bool(background),
            "hint": "各成员 run 已按名册派生（背景执行用 subagent_status 轮询；"
                    "依赖门按 taskUnit.dependencies 步间编排）" if background else
                    "各成员 run 已按名册派生并等待完成",
            **self._quota_snapshot(),
        }

    def _resolveTeamMember(
        self, teamId: Optional[str], teamRole: Optional[str], task: str,
    ) -> tuple:
        """S9 动态组队：按团队名册选人（不引入角色辩护等重机制）。

        匹配顺序：角色命中（member.role == teamRole，或职责 prompt 含角色值）→
        任务文本点名（成员显示名 / user_id）→ 首个有职责 prompt 的成员 → 首个成员。
        数据单源 = teams_api 的 JSON 落盘（``getTeamRoster`` 只读），不另建团队存储。

        Returns:
            (member dict 或 None, rejection dict 或 None)——rejection 非 None 时
            spawn 直接结构化拒绝（TEAM_UNKNOWN / TEAM_EMPTY / TEAM_ROLE_UNKNOWN）。
        """
        if not teamId:
            return None, None
        from neurova.agent.templates.collaboration_template import AgentRole
        from neurova.api.endpoints.teams_api import getTeamRoster

        roster = getTeamRoster(teamId)
        if roster is None:
            return None, self._rejection("TEAM_UNKNOWN", f"团队不存在: {teamId}")
        members = [m for m in (roster.get("members_detail") or [])
                   if str(m.get("user_id") or "").strip()]
        if not members:
            return None, self._rejection(
                "TEAM_EMPTY", f"团队 {teamId} 名册为空——请先添加团队成员")
        roleValue = str(teamRole or "").strip()
        if roleValue and roleValue not in {r.value for r in AgentRole}:
            return None, self._rejection(
                "TEAM_ROLE_UNKNOWN",
                f"未知团队角色 {roleValue!r}（可选：{', '.join(r.value for r in AgentRole)}）")
        selected: Optional[Dict[str, Any]] = None
        if roleValue:
            for m in members:
                if (str(m.get("role") or "") == roleValue
                        or roleValue in str(m.get("prompt") or "")):
                    selected = m
                    break
        if selected is None:
            for m in members:
                name = str(m.get("name") or "")
                uid = str(m.get("user_id") or "")
                if (name and name in task) or (uid and uid in task):
                    selected = m
                    break
        if selected is None:
            for m in members:
                if str(m.get("prompt") or "").strip():
                    selected = m
                    break
        return (selected or members[0]), None

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
        result = run.to_dict()
        # B4 管理面：排队中的 run 随状态投影透出队列位次（0=不在队列）。
        result["queue_position"] = _runQueue().position(subagent_id)
        return result

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

    # ── H-4：run 级事件归档（JSONL 账本，因果链沿 last_event_id 串接）──

    #: 谱系上溯限深（防异常环拖垮事件写入；16 层远超派生深度治理上限）
    LINEAGE_WALK_LIMIT = 16

    def _runLineage(self, run: SubAgentRun) -> Dict[str, Any]:
        """F5 谱系投影：事件写入时现算（不落存储字段，设计文档 §3.5）。

        agent_path 沿 ``parent_subagent_id`` 在内存 run 表上溯、根→叶顺序；
        父 run 已被逐出/不在内存时其 id 仍入路径（谱系不断链）；
        限深 16、访问集防环。
        """
        chain: List[str] = []  # 叶→根
        visited: set = set()
        cursor: Optional[SubAgentRun] = run
        while cursor is not None and len(chain) < self.LINEAGE_WALK_LIMIT:
            sid = str(cursor.subagent_id or "")
            if not sid or sid in visited:
                break
            visited.add(sid)
            chain.append(sid)
            parentId = str(getattr(cursor, "parent_subagent_id", "") or "")
            if not parentId or parentId in visited:
                break
            parent = self._runs.get(parentId)
            if parent is None:
                # 父 run 不在内存（已逐出/跨进程）：id 仍入路径后停止上溯
                chain.append(parentId)
                visited.add(parentId)
                break
            cursor = parent
        chain.reverse()  # 根→叶
        return {
            "tenant_id": run.tenant_id,
            "team_id": run.team_id,
            "project_id": run.project_id,
            "room_id": run.room_id,
            "depth": run.depth,
            "parent_subagent_id": run.parent_subagent_id,
            "agent_path": chain,
            "trace_id": run.trace_id,
            "parent_trace_id": run.parent_trace_id,
        }

    def _logRunEvent(self, run: SubAgentRun, eventType: str,
                     payload: Optional[Dict[str, Any]] = None) -> None:
        """run 生命周期事件入归档；fail-open（归档故障不阻断蜂群主流程）。

        F5：全部 run 事件统一携带 lineage 谱系（spawned/started/terminal/
        cancelled/tool_call/member_chunk/permission_decided… 自动带上）。
        A2：同事件镜像进全局事件库（全局单调 seq，重放/快照协议用）——
        JSONL 账本仍是一手事实源，镜像 fail-open 不阻断主流程。
        """
        # A5 终态助推：terminal 事件是全部终态迁移的统一收口（成败/超时/取消/
        # 队列取消都从这里落）——在此把下次结算扫掠提前（开关开才调度，fail-open）。
        if eventType == "terminal":
            self._scheduleSettleBoost()
        try:
            from neurova.agent.swarm_event_log import appendRunEvent

            eventId = appendRunEvent(
                run.subagent_id, eventType, payload,
                causationId=getattr(run, "last_event_id", ""),
                lineage=self._runLineage(run),
            )
            run.last_event_id = eventId
            try:
                _eventStore().append(
                    str(run.subagent_id or ""), eventType,
                    dict(payload or {}), event_id=str(eventId or ""),
                )
            except Exception as mirrorError:  # noqa: BLE001 - 镜像 fail-open
                logger.debug("Swarm: 事件库镜像失败 (%s/%s): %s",
                             run.subagent_id, eventType, mirrorError)
        except Exception as e:  # noqa: BLE001
            logger.debug("Swarm: 事件归档失败 (%s/%s): %s", run.subagent_id, eventType, e)

    def runEvents(self, subagent_id: str) -> Dict[str, Any]:
        """H-4 读侧：按 run 取事件账本（事件因果链完整保留；账本独立于内存
        逐出——run 被逐出后仍可查）。未知/无事件的 run 返回空列表。"""
        sid = str(subagent_id or "").strip()
        from neurova.agent.swarm_event_log import readRunEvents

        events = readRunEvents(sid) if sid else []
        return {"subagent_id": sid, "count": len(events), "events": events}

    def memberSurface(self, subagentId: str):
        """C2 接线（G3 收敛面）：按 subagent_id 解析成员操作面（读面共用单点）。

        run 在内存台账 → ``NeuacpMemberSurface.forRun``（能力档来自名册现值/
        spawn 快照）；已逐出的存量 run → 以最小标识 run 补位（事件账本读数
        不依赖名册档，读数行为与逐出前一致）。未知 id 也返回面——账本读侧对
        未知 run 返回空列表（与 runEvents 同口径），写操作由各面按缺标识诚实
        失败（如 rollback 缺 agent_id/member_session_id）。
        """
        from neurova.agent.neuacp.adapter_surface import NeuacpMemberSurface

        sid = str(subagentId or "").strip()
        with self._lock:
            run = self._runs.get(sid)
        if run is None:
            run = SubAgentRun(subagent_id=sid)
        return NeuacpMemberSurface.forRun(run)

    def settleIdleRuns(self, *, now_ts: Optional[float] = None,
                       force: bool = False) -> Dict[str, Any]:
        """A5：闲置终态 run 自动收敛。三个驱动入口：

        - 时钟驱动：TaskScheduler 每小时 job（开关开才挂，默认关）；
        - 显式驱动：``settleIdleRunsNow()``（admin 端点 POST /v1/swarm-queue/settle），
          ``force=True`` 不受开关限制；
        - 终态助推：run 落终态时把下次扫掠提前（``_settleBoostTick`` 到期即跑）。

        结算语义按本仓状态机裁剪：completed/failed 已是终态且无出边，**不新增
        "settled" 状态词**——结算动作 = 把闲置超阈值的终态 run 从内存台账逐出
        （事件/帧/归档账本在磁盘，逐出后仍可查）并留痕 `auto_settled` 事件。
        护栏与阈值判定单源在 run_settlement.evaluateSettlement（任何驱动都不豁免）；
        开关 NEUROVA_SWARM_AUTO_SETTLE 默认关（D-C 拍板），阈值
        NEUROVA_SWARM_SETTLE_IDLE_DAYS 默认 3 天。
        """
        from neurova.agent.run_settlement import (
            SettlementCandidate,
            readSettleSettings,
            sweep,
        )

        enabled, idleDays = readSettleSettings()
        if not enabled and not force:
            return {"enabled": False, "settled": [], "skipped": [], "failed": []}
        now = float(now_ts) if now_ts is not None else time.time()
        candidates: List[Any] = []
        with self._lock:
            runs = list(self._runs.values())
        for run in runs:
            if run.status not in SUBAGENT_FINISHED_STATUSES:
                continue
            finishedAt = float(getattr(run, "finished_at", 0) or 0)
            candidates.append(SettlementCandidate(
                subagent_id=str(run.subagent_id or ""),
                status=str(run.status or ""),
                last_activity_at=finishedAt,
                guards={
                    "active_run": False,   # 已终态
                    "pending_approval": any(
                        str((entry or {}).get("status") or "") == "pending"
                        for entry in (getattr(run, "approvals", None) or [])
                    ),
                    "pinned": False,           # 本仓 run 无置顶概念
                    "explicit_override": False,
                    "queued_turn": False,      # 终态 run 无排队轮
                    "snoozed": False,          # 本仓 run 无 snooze 概念
                    "background_work": False,  # 终态即后台工作已收口
                    "grace_period": bool(finishedAt) and (now - finishedAt) < 120.0,
                },
            ))

        def _settle(subagentId: str) -> None:
            with self._lock:
                run = self._runs.pop(subagentId, None)
            if run is not None:
                self._logRunEvent(run, "auto_settled", {
                    "idle_days": idleDays,
                    "status": run.status,
                    "finished_at": run.finished_at,
                })

        return sweep(candidates, now_ts=now, idle_days=idleDays, settle_fn=_settle)

    def settleIdleRunsNow(self, *, now_ts: Optional[float] = None) -> Dict[str, Any]:
        """A5 显式驱动：管理面（POST /v1/swarm-queue/settle）显式触发一次结算。

        不受 NEUROVA_SWARM_AUTO_SETTLE 默认关限制——admin 显式调用即执行；
        九重护栏与闲置阈值照常生效（force 只越过开关，不豁免护栏）。
        返回结算结果三桶（settled/skipped/failed）。
        """
        return self.settleIdleRuns(now_ts=now_ts, force=True)

    def _scheduleSettleBoost(self) -> None:
        """A5 终态助推：run 落终态且开关开时，把下次扫掠提前 60s。

        TaskScheduler 只支持固定周期 job（addSystemJob=IntervalTrigger，无一次性
        job），故用「到期时间戳」模式：这里只更新 _nextSweepDue（多次终态取最早
        到期）并确保 60s 轻量 job 在册；到点扫掠由 _settleBoostTick 执行。全程
        fail-open：助推注册失败不阻断终态事件归档。
        """
        try:
            from neurova.agent.run_settlement import (
                SETTLE_BOOST_DELAY_SECONDS,
                SETTLE_BOOST_JOB_ID,
                readSettleSettings,
            )

            if not readSettleSettings()[0]:
                return
            now = time.time()
            with self._lock:
                due = now + SETTLE_BOOST_DELAY_SECONDS
                if self._nextSweepDue <= 0 or due < self._nextSweepDue:
                    self._nextSweepDue = due
                alreadyRegistered = self._settleBoostJobRegistered
                self._settleBoostJobRegistered = True
            if not alreadyRegistered:
                from neurova.agent.scheduler import get_scheduler

                get_scheduler().addSystemJob(
                    self._settleBoostTick, SETTLE_BOOST_JOB_ID,
                    int(SETTLE_BOOST_DELAY_SECONDS))
        except Exception as boostError:  # noqa: BLE001 - 助推失败不阻断终态落账
            logger.debug("Swarm: 终态助推调度失败: %s", boostError)

    def _settleBoostTick(self) -> None:
        """A5 终态助推的 60s 轻量 job：到点查 _nextSweepDue，到期即跑一轮结算。"""
        now = time.time()
        with self._lock:
            due = self._nextSweepDue
            if due <= 0 or now < due:
                return
            self._nextSweepDue = 0.0  # 到期消费，跑完不重复助推
        try:
            self.settleIdleRuns()
        except Exception as tickError:  # noqa: BLE001 - 助推扫掠失败不炸调度线程
            logger.debug("Swarm: 终态助推扫掠失败: %s", tickError)

    def runFrames(self, subagent_id: str, afterSeq: int = 0,
                  limit: int = 1000) -> Dict[str, Any]:
        """F2 帧账本读侧（管理器统一入口，镜像 runEvents 形态）：按 seq 游标
        回放一手帧流（原生帧脱敏后留痕，读逻辑单源在 frame_log.readFrames）。
        未知/无帧的 run 返回空列表。"""
        sid = str(subagent_id or "").strip()
        from neurova.agent.neuacp.frame_log import readFrames

        frames = readFrames(sid, afterSeq=afterSeq, limit=limit) if sid else []
        return {"subagent_id": sid, "count": len(frames), "frames": frames}

    def reconcileRunFromEvents(self, subagent_id: str,
                               tailOverride: str = "") -> Dict[str, Any]:
        """S3 启动收敛增强：用事件账本末态校正内存 run 的漂移（补强，不替代台账）。

        内存无此 run → 如实报告（重启后常态，不凭账本复活对象）；一致 → noop；
        漂移 → 按账本末态直改并落一条 status_corrected 事件留痕。校正不是生命
        周期迁移（重启期间账本可能推进到迁移表不可达的跳变，如 running→completed
        的跨相位补账），故不走 transitionRun，但必须留痕可查。

        `tailOverride`：调用方已重放/归一化好的末态（启动收敛入口
        reconcileSwarmRunsAtStartup 传入，免二次读账本）；缺省现场重放。
        """
        sid = str(subagent_id or "").strip()
        tail = str(tailOverride or "").strip() or replayRunTailStatus(sid)
        with self._lock:
            run = self._runs.get(sid)
            if run is None:
                return {"subagent_id": sid, "corrected": False,
                        "reason": "not_in_memory", "event_tail_status": tail}
            if tail not in SUBAGENT_STATUSES:
                return {"subagent_id": sid, "corrected": False,
                        "reason": "no_event_tail" if not tail else "invalid_tail_status",
                        "status": run.status, "event_tail_status": tail}
            if run.status == tail:
                return {"subagent_id": sid, "corrected": False, "reason": "consistent",
                        "status": run.status, "event_tail_status": tail}
            before = run.status
            run.status = tail
            self._logRunEvent(run, "status_corrected",
                              {"from": before, "to": tail, "cause": "event_log_replay"})
            return {"subagent_id": sid, "corrected": True, "from": before, "to": tail}

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
        board = self._candidates.snapshot()
        candidatesSource = "live"
        if not board["candidates"] and not board["conflicts"]:
            # P2-3 兜底（拍板 D-C）：内存板为空（重启/他进程场景）时以 H-4 账本
            # 重放投影补齐——账本仍是唯一持久层，这里只读不写、不建第二事实源，
            # 不改候选板 CAS 语义与判定权（处置仍只认内存板）。
            try:
                from neurova.agent.candidate_projection import projectCandidateBoard
                from neurova.agent.swarm_event_log import readRunEvents

                sids = [r.subagent_id for r in runs]
                replay = projectCandidateBoard(
                    {sid: readRunEvents(sid) for sid in sids if sid})
                if replay["candidates"] or replay["conflicts"]:
                    board = {"revision": replay["revision"],
                             "candidates": replay["candidates"],
                             "conflicts": replay["conflicts"]}
                    candidatesSource = "replay"
            except Exception as e:  # noqa: BLE001 - 投影故障不阻断核对面（留 debug 痕）
                logger.debug("Swarm: 候选重放投影失败（按内存空板报告）: %s", e)
        return {
            "integration_ready": not blockers,
            "blockers": blockers,
            "blocked_count": len(blocked),
            "subtasks": subtasks,
            # S4 结果候选制：集成版本（CAS 基准）、在途/已裁候选、冲突清单
            "revision": board["revision"],
            "candidates": board["candidates"],
            "conflicts": board["conflicts"],
            # P2-3：候选来源——live=内存板单源；replay=H-4 账本重放投影（内存板空时）
            "candidates_source": candidatesSource,
        }

    # ── S4：结果候选制（member 产出先落候选，主侧审批 + CAS 合入）────────

    def _submitResultCandidate(self, run: SubAgentRun, report: str):
        """member 结果回传先落候选（submitted）——不直接定案。

        artifactKeys 取自 TaskUnit.artifactOwnership（该结果主张触碰的产物/记忆键）；
        同 key 同基准的候选在提交时即互相标记冲突（都保留），并升级人工裁决。
        """
        from neurova.agent.candidate_merge import artifactKeysFromOwnership

        unit = run.task_unit or {}
        keys = artifactKeysFromOwnership(str(unit.get("artifactOwnership") or ""))
        candidate = self._candidates.submitCandidate(
            runId=run.subagent_id, content=report, artifactKeys=keys)
        self._logRunEvent(run, "candidate_submitted", {
            "candidate_id": candidate.candidateId,
            "base_revision": candidate.baseRevision,
            "artifact_keys": keys,
        })
        # S9：候选提交事件上墙（人工可拦截的产品面）
        self._notifyRoomCandidateSafe(run, "submitted", candidate.candidateId,
                                      detail=f"baseRevision={candidate.baseRevision}")
        if candidate.conflictWith:
            self._logRunEvent(run, "candidate_conflict_flagged", {
                "candidate_id": candidate.candidateId,
                "conflict_with": list(candidate.conflictWith),
            })
            self._notifyRoomCandidateSafe(run, "conflict", candidate.candidateId,
                                          detail=f"冲突对象 {list(candidate.conflictWith)}")
            self.recordEscalation(
                run, reason="merge_conflict",
                question=f"候选 {candidate.candidateId} 与 {list(candidate.conflictWith)}"
                         " 主张同一产物且基准版本相同，需人工裁决采纳哪份",
                severity="high", suggestedAction="clarify")
        return candidate

    def _notifyRoomCandidateSafe(self, run: SubAgentRun, status: str,
                                 candidateId: str, detail: str = "") -> None:
        """候选状态事件投协作房间（run 无房间时为空操作；故障不上抛）。"""
        try:
            from neurova.agent.approval_chain import notifyRoomCandidate

            notifyRoomCandidate(run, status, candidateId, detail=detail)
        except Exception as e:  # noqa: BLE001 - 房间呈现失败不影响候选主流程
            logger.debug("Swarm: 候选事件房间投递失败 (%s/%s): %s",
                         candidateId, status, e)

    def _rejectCandidateForRun(self, run: SubAgentRun, candidate, reason: str) -> None:
        """验收/评审驳回：候选置 reviseRequired（回炉走既有链），事件留痕。"""
        try:
            self._candidates.markReviseRequired(candidate.candidateId, reason)
        except Exception as e:  # noqa: BLE001 - 候选板故障不改写验收结论
            logger.debug("Swarm: 候选置 reviseRequired 失败 (%s): %s",
                         candidate.candidateId, e)
        self._logRunEvent(run, "candidate_revise_required", {
            "candidate_id": candidate.candidateId,
            "reason": str(reason or "")[:EVENT_ERROR_SUMMARY_CHARS],
        })

    async def _mergeCandidateForRun(self, run: SubAgentRun, candidate) -> Dict[str, Any]:
        """主侧合入候选：审批链分级（默认 L0 自动留痕）+ CAS；冲突升级人工裁决。

        Returns:
            merged=True → 已合入（run 可定案 completed）；
            merged=False → cause=merge_conflict/merge_blocked/merge_failed，
            候选保留在板上，run 如实判失败（结果未入集成）。
        """
        from neurova.agent.candidate_merge import (
            CandidateConflictError,
            CandidateMergeError,
        )

        approved, approvalNote = await self._approveMerge(run, candidate)
        if not approved:
            return {"merged": False, "cause": "merge_blocked",
                    "error": f"结果合入未获准（{approvalNote}）；候选保留待人工处置"}
        try:
            outcome = self._candidates.mergeCandidate(candidate.candidateId)
        except CandidateConflictError as e:
            self._logRunEvent(run, "candidate_conflict", {
                "candidate_id": candidate.candidateId,
                "detail": str(e)[:EVENT_ERROR_SUMMARY_CHARS],
            })
            self._notifyRoomCandidateSafe(run, "conflict", candidate.candidateId,
                                          detail=str(e)[:EVENT_ERROR_SUMMARY_CHARS])
            self.recordEscalation(
                run, reason="merge_conflict",
                question=f"候选 {candidate.candidateId} CAS 合入冲突：{e}",
                severity="high", suggestedAction="clarify")
            return {"merged": False, "cause": "merge_conflict",
                    "error": f"结果合入冲突（候选已保留并升级人工裁决）：{e}"}
        except CandidateMergeError as e:
            self._logRunEvent(run, "candidate_merge_rejected", {
                "candidate_id": candidate.candidateId,
                "detail": str(e)[:EVENT_ERROR_SUMMARY_CHARS],
            })
            self._notifyRoomCandidateSafe(run, "merge_failed", candidate.candidateId,
                                          detail=str(e)[:EVENT_ERROR_SUMMARY_CHARS])
            return {"merged": False, "cause": "merge_failed",
                    "error": f"结果合入被拒：{e}"}
        self._logRunEvent(run, "candidate_merged", {
            "candidate_id": candidate.candidateId,
            "revision": outcome.get("revision"),
            "approval": approvalNote,
        })
        self._notifyRoomCandidateSafe(run, "merged", candidate.candidateId,
                                      detail=f"revision={outcome.get('revision')}")
        return {"merged": True, "revision": outcome.get("revision")}

    async def _approveMerge(self, run: SubAgentRun, candidate) -> tuple:
        """merge 动作纳入既有审批链（L0 自动放行留痕；env 可调 L1/L2）。

        审批通道故障时按放行留痕处理（warning 可见 + merged 事件带 approval
        注记）——候选板与事件账本仍完整可查，集成主流程不因审批基础设施抖动
        而卡死；审批分级本身不受影响（L1/L2 的等待与拒绝语义照常生效）。
        """
        import os as _os

        from neurova.agent.approval_chain import requestRunApproval

        raw = (_os.environ.get(MERGE_APPROVAL_LEVEL_ENV) or "").strip().upper()
        level = raw if raw in ("L0", "L1", "L2") else "L0"
        try:
            verdict = await requestRunApproval(
                run,
                action=f"merge_candidate:{candidate.candidateId}",
                reason=(f"合入子任务结果候选（run={run.subagent_id}，"
                        f"baseRevision={candidate.baseRevision}）"),
                level=level,
                context="swarm_candidate_merge",
            )
            if verdict.get("approved"):
                return True, f"approved:{verdict.get('level', level)}"
            return False, (verdict.get("pending_reason")
                           or verdict.get("status") or "not_approved")
        except Exception as e:  # noqa: BLE001 - 审批通道故障不阻断集成（留痕可见）
            logger.warning("Swarm: merge 审批通道故障，按放行留痕处理 (%s): %s",
                           candidate.candidateId, e)
            return True, "approval_channel_unavailable"

    def applyRoomCandidateAction(self, candidateId: str, action: str, actor: str = "") -> Dict[str, Any]:
        """S9：人在房间对候选的直接处置（拦截=否决 / 采纳=CAS 合入）。

        判定权仍在候选板单源（CandidateMergeBoard），房间只是应答入口；
        采纳走 CAS 合入——冲突时候选保留、如实返回冲突（不静默覆盖）。
        """
        from neurova.agent.candidate_merge import CandidateConflictError, CandidateMergeError

        act = str(action or "").strip().lower()
        if act not in ("intercept", "merge"):
            return {"success": False, "error": "action 仅支持 intercept/merge"}
        candidate = self._candidates.candidate(candidateId)
        if candidate is None:
            return {"success": False, "error": f"候选不存在: {candidateId}"}
        run = self._runs.get(candidate.runId)
        if act == "intercept":
            rejected = self._candidates.rejectCandidate(
                candidateId, reason=f"房间拦截（by {actor or '群主'}）")
            if run is not None:
                self._logRunEvent(run, "candidate_rejected", {
                    "candidate_id": candidateId, "by": "room", "actor": str(actor or ""),
                })
                self._notifyRoomCandidateSafe(run, "rejected", candidateId,
                                              detail=f"房间拦截（by {actor or '群主'}）")
            return {"success": True, "action": "intercept",
                    "candidate_id": candidateId, "status": rejected.status}
        try:
            outcome = self._candidates.mergeCandidate(candidateId)
        except CandidateConflictError as e:
            if run is not None:
                self._notifyRoomCandidateSafe(run, "conflict", candidateId,
                                              detail=str(e)[:EVENT_ERROR_SUMMARY_CHARS])
            return {"success": False, "action": "merge", "conflict": True,
                    "candidate_id": candidateId, "error": str(e)}
        except CandidateMergeError as e:
            return {"success": False, "action": "merge",
                    "candidate_id": candidateId, "error": str(e)}
        if run is not None:
            self._logRunEvent(run, "candidate_merged", {
                "candidate_id": candidateId, "revision": outcome.get("revision"),
                "approval": f"room_action_by:{actor or '群主'}",
            })
            self._notifyRoomCandidateSafe(run, "merged", candidateId,
                                          detail=f"revision={outcome.get('revision')}")
        return {"success": True, "action": "merge", "candidate_id": candidateId,
                "revision": outcome.get("revision")}

    def candidateRecordsForRuns(self, runIds: List[str]) -> List[Dict[str, Any]]:
        """S12 档案读面：按 run 集合取候选记录（候选板单源读面，供读时 join）。

        只读不改；runIds 为空返回空表。返回 toDict 投影——content 是候选定稿
        正文引用，档案层按脱敏纪律截断展示，不搬运大正文。
        """
        wanted = {str(r or "").strip() for r in (runIds or []) if str(r or "").strip()}
        if not wanted:
            return []
        return [c.toDict() for c in self._candidates.allCandidates() if c.runId in wanted]

    # ── P1-4（评测报告 G-4）：依赖门控 ──────────────────────────

    def _depSatisfied(self, run: SubAgentRun) -> bool:
        """依赖放行判据（η 门）：终态 completed 且验收门未判不达标，且终态可信。

        A1 终态质量分级消费点：weak/none 终态（超时/取消兜底、来路不明）的
        completion 不算合格输入——上层不得把弱终态当强终态消费，须先复核；
        历史空值（直接构造、未经 transitionRun 收口）维持原放行行为（向后兼容）。
        验收灰度关闭时 acceptance 为 None → 退化为"completed 即放行"（判据弱化但门仍在）；
        验收 failed/skipped-judge 的产出不是合格输入（skipped 是诚实降级，仍放行）。
        """
        if run.status != SUBAGENT_COMPLETED:
            return False
        if requiresReviewConfirmation(run):
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
        # B3：外部成员的适配器在 blocked 登记时已解析（外部 id 不在 Agent
        # 注册表，_resolve_agent 会错拿默认兜底）——放行时原样续用。
        externalAdapter = info.get("external_adapter")
        if externalAdapter is not None:
            agent, resolved_id, _fallback = externalAdapter, str(info["agent_id"]), False
        else:
            agent, resolved_id, _fallback = self._resolve_agent(info["agent_id"])
        model = self._resolve_model_name(agent) if agent is not None else ""
        # D-B：blocked 放行的外部成员同样在落 run 时冻结执行体档案（与主
        # spawn 同口径；登记时的 team_id 已随等待件携带）。
        executorProfile = (
            self._executorProfileFor(str(info["agent_id"]), info.get("team_id"))
            if externalAdapter is not None else None
        )
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
            room_id=info.get("room_id") or "",
            project_id=info.get("project_id") or "",
            team_id=info.get("team_id") or "",
            team_role=info.get("team_role") or "",
            team_member=info.get("team_member"),
            runtime_budget_sec=float(info.get("runtime_budget_sec") or 0.0),
            # D-B：spawn 时刻执行体档案快照（外部成员专有；本仓 agent 为 None/""）
            executor_caps_snapshot=dict(executorProfile["caps"]) if executorProfile else None,
            executor_tool=executorProfile["tool"] if executorProfile else "",
            executor_model=model or "",
            # F5 谱系：blocked 放行时父链取 spawn（登记）时刻的固定值
            tenant_id=self._currentTenantId(),
            parent_subagent_id=info.get("parent_subagent_id") or "",
        )
        with self._lock:
            self._runs[run.subagent_id] = run
            # B3：放行的外部成员同样登记适配器（cancelRun 传导链不断）
            if externalAdapter is not None:
                self._externalAdapters[run.subagent_id] = (
                    externalAdapter, asyncio.get_running_loop())
        self._logRunEvent(run, "spawned", {
            "task": run.task[:EVENT_TASK_SUMMARY_CHARS], "origin": run.origin, "depth": run.depth,
            "subagent_type": run.subagent_type, "model": run.model,
            "parent_trace_id": run.parent_trace_id,
        })
        # B4：blocked 放行的 run 与主 spawn 同点入排队管理面
        self._registerRunQueue(run)
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
        # D-B：依赖门判失败的 run 也落执行体档案快照（外部成员专有）——该 run
        # 终态可续跑，续跑决策需要与 spawn（登记）时刻同口径的快照。
        failedProfile = (
            self._executorProfileFor(str(info.get("agent_id") or ""), info.get("team_id"))
            if info.get("external_adapter") is not None else None
        )
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
            room_id=info.get("room_id") or "",
            project_id=info.get("project_id") or "",
            team_id=info.get("team_id") or "",
            team_role=info.get("team_role") or "",
            team_member=info.get("team_member"),
            # D-B：spawn（登记）时刻执行体档案快照；未执行过，模型名留空
            executor_caps_snapshot=dict(failedProfile["caps"]) if failedProfile else None,
            executor_tool=failedProfile["tool"] if failedProfile else "",
            executor_model="",
            # F5 谱系：同 blocked 登记时刻的固定值
            tenant_id=self._currentTenantId(),
            parent_subagent_id=info.get("parent_subagent_id") or "",
        )
        transitionRun(run, SUBAGENT_FAILED, cause="dependency_failed")
        run.cause = "dependency_failed"
        run.error = (f"dependency_failed（前置 {upstream.subagent_id} 未验收通过："
                     f"{upstream.status}）；本任务未执行，请修复或重派前置后重新派生")
        run.finished_at = time.time()
        with self._lock:
            self._runs[bid] = run
            self._evict_finished_runs()
        self._logRunEvent(run, "spawned", {"task": run.task[:EVENT_TASK_SUMMARY_CHARS],
                                           "origin": run.origin,
                                           "depth": run.depth, "blocked": True})
        self._logRunEvent(run, "terminal", {"status": run.status, "cause": run.cause,
                                            "error": (run.error or "")[:EVENT_ERROR_SUMMARY_CHARS]})

    # ── H 批补差（异步任务更新/叫停对照批）──────

    def cancelRun(self, subagent_id: str, reason: str = "", command_id: Optional[str] = None) -> Dict[str, Any]:
        """父侧叫停一个子代理运行（A3 回执幂等包装）。

        ``command_id`` 非空时走命令回执（同 ID 重试重放结果、不重复执行取消
        副作用）；空（缺省）保持原行为。
        """
        cid = str(command_id or "").strip()
        if not cid:
            return self._cancelRunInner(subagent_id, reason=reason)
        from neurova.core.command_receipt import executeWithReceipt

        try:
            result, replayed = executeWithReceipt(
                _receiptConnection(),
                command_id=cid,
                command_type="cancel_run",
                thread_id=str(subagent_id or ""),
                fn=lambda: self._cancelRunInner(subagent_id, reason=reason),
            )
        except Exception as exc:  # noqa: BLE001 - 回执三态错误如实转拒绝结构
            return _receiptRejection(exc)
        if replayed:
            result = dict(result or {})
            result["replayed"] = True
        return result

    def _cancelRunInner(self, subagent_id: str, reason: str = "") -> Dict[str, Any]:
        """父侧叫停一个子代理运行。

        - 运行中（pending/running/in_review）：取消其 asyncio 任务——CancelledError
          路径的既有收尾（failed/subagent_cancelled 落账、释放槽位、部分报告交接、
          依赖结算）照常生效；
        - blocked 等待件：未启动执行，直接判失败落账（移出等待册，依赖结算不再拉起）；
        - 已终态/未知 id：幂等失败（诚实报错）；
        - 前台运行（父回合内 await，无独立任务句柄）：如实报错不可单独叫停。
        """
        sid = str(subagent_id or "").strip()
        if not sid:
            return {"success": False, "error": "subagent_id 不能为空"}
        with self._lock:
            run = self._runs.get(sid)
            blocked = self._blocked.pop(sid, None) if run is None else None
        if run is None and blocked is None:
            return {"success": False, "error": f"未找到子 Agent 运行记录: {sid}"}
        if run is None:
            # D-B：blocked 等待件被叫停也落执行体档案快照（外部成员专有）——
            # 该 run 落终态后仍可续跑，续跑决策需要与登记时刻同口径的快照。
            blockedProfile = (
                self._executorProfileFor(str(blocked.get("agent_id") or ""),
                                         blocked.get("team_id"))
                if blocked.get("external_adapter") is not None else None
            )
            failed = SubAgentRun(
                subagent_id=sid, depth=blocked.get("depth", 1),
                agent_id=blocked.get("agent_id", ""),
                agent_name=blocked.get("agent_name") or blocked.get("agent_id", ""),
                task=blocked.get("task", ""),
                origin=blocked.get("origin", "chat"),
                session_id=blocked.get("session_id"),
                node_id=blocked.get("node_id"),
                execution_id=blocked.get("execution_id"),
                subagent_type=blocked.get("subagent_type", "general"),
                task_unit=blocked.get("task_unit"),
                parent_trace_id=blocked.get("parent_trace_id", ""),
                team_id=str(blocked.get("team_id") or ""),
                # D-B：spawn（登记）时刻执行体档案快照；未执行过，模型名留空
                executor_caps_snapshot=dict(blockedProfile["caps"]) if blockedProfile else None,
                executor_tool=blockedProfile["tool"] if blockedProfile else "",
                executor_model="",
                # F5 谱系：同 blocked 登记时刻的固定值
                tenant_id=self._currentTenantId(),
                parent_subagent_id=blocked.get("parent_subagent_id", ""),
            )
            transitionRun(failed, SUBAGENT_FAILED, cause=SUBAGENT_CAUSE_CANCELLED)
            failed.cause = SUBAGENT_CAUSE_CANCELLED
            failed.error = "subagent_cancelled（依赖等待中被叫停，未启动执行）"
            failed.finished_at = time.time()
            with self._lock:
                self._runs[sid] = failed
                self._evict_finished_runs()
            self._logRunEvent(failed, "cancelled", {
                "reason": str(reason or "")[:160], "phase": "blocked"})
            return {"success": True, "subagent_id": sid, "status": failed.status,
                    "cancelled": True, "note": "等待依赖中被叫停，未启动执行"}
        if run.status in SUBAGENT_FINISHED_STATUSES:
            return {"success": False,
                    "error": f"子代理已终态（{run.status}），无需叫停"}
        with self._lock:
            task = self._tasks.get(sid)
        if task is None:
            return {"success": False,
                    "error": "该子任务随父回合前台阻塞运行，无独立任务句柄可叫停"
                             "（如需可停，请以 background=true 派生）"}
        run.cancel_note = str(reason or "").strip() or "父代理主动叫停"

        # 取消落账兜底：若 cancel 早于成员任务的首个执行步，协程体从未运行，
        # CancelledError 处理器不会执行——这里在任务收尾时把 run 如实判为
        # cancelled 终态（幂等：协程处理器已落账则跳过）。
        def _finalizeCancelled(_task) -> None:
            if run.status in SUBAGENT_ACTIVE_STATUSES:
                transitionRun(run, SUBAGENT_FAILED, cause=SUBAGENT_CAUSE_CANCELLED)
                run.cause = SUBAGENT_CAUSE_CANCELLED
                run.error = f"subagent_cancelled（{run.cancel_note}；任务未产出）"
                run.finished_at = time.time()
                with self._lock:
                    self._evict_finished_runs()
                self._release_slot(run)
                self._logRunEvent(run, "terminal", {
                    "status": run.status, "cause": run.cause,
                    "error": run.error[:EVENT_ERROR_SUMMARY_CHARS]})
                self._settleDependencies(run)

        # 跨线程投递必须走 call_soon_threadsafe：cancelRun 可能在无事件循环的
        # 线程被调（工具/API 线程），task.cancel()/add_done_callback() 内部的
        # call_soon 不唤醒 spawnLoop——若外部传导（run_coroutine_threadsafe）
        # 先唤醒循环并抢先收尾任务，随后的回调登记将无人唤醒，兜底落账
        # _finalizeCancelled 迟迟不执行（实测 status 停在 pending）。先挂
        # 回调再发取消，保证终态落账必达。
        taskLoop = task.get_loop()
        taskLoop.call_soon_threadsafe(task.add_done_callback, _finalizeCancelled)
        taskLoop.call_soon_threadsafe(task.cancel)
        # B3：外部成员把叫停同步传导进外部代理进程（task.cancel 只取消本仓侧
        # 的等待协程，外部子进程仍在跑——必须经 adapter.cancel 发 session/cancel）。
        self._cancelExternalMember(sid)
        self._logRunEvent(run, "cancelled", {"reason": run.cancel_note})
        return {"success": True, "subagent_id": sid, "status": "cancelling",
                "hint": "取消已发出；终态将以 failed(subagent_cancelled) 落账，"
                        "subagent_status 可确认"}

    def _cancelExternalMember(self, sid: str) -> None:
        """B3：向外部编码代理成员传导叫停（cancelRun → adapter.cancel →
        executor.cancel → ACP session/cancel）。

        best-effort：叫停主信号是 ``task.cancel()``（本仓侧等待协程照常取消
        收账）；这里负责让外部子进程也停下来。cancelRun 可能在无事件循环的
        线程被调（工具/API 线程）——协程经 spawn 时登记的循环投递；投递失败
        （循环已关等）记 debug，不影响取消主流程。
        """
        with self._lock:
            registered = self._externalAdapters.get(sid)
        if registered is None:
            return
        adapter, spawnLoop = registered
        try:
            runningLoop = asyncio.get_running_loop()
        except RuntimeError:
            runningLoop = None
        try:
            if runningLoop is not None:
                runningLoop.create_task(adapter.cancel())
            else:
                asyncio.run_coroutine_threadsafe(adapter.cancel(), spawnLoop)
            logger.info("Swarm: 外部成员叫停已传导 (subagent_id=%s)", sid)
        except Exception as e:  # noqa: BLE001 - 传导失败不阻断取消主流程
            logger.debug("Swarm: 外部成员叫停传导失败 (subagent_id=%s): %s", sid, e)

    def rollbackSubagent(self, subagent_id: str,
                         command_id: Optional[str] = None) -> Dict[str, Any]:
        """C2 接线（G3 收敛面）：把子代理 member 会话回滚到最近检查点。

        机制全在 ``NeuacpMemberSurface.rollback``（CheckpointService 事务化
        恢复：恢复前自动留 pre-restore 快照、apply 失败自动回滚；能力闸
        conversation_rollback 在面内 fail-closed）。本方法只做 run 解析、
        能力未声明的转译（CapabilityNotDeclared → 结构化拒绝）与事件留痕。
        ``command_id`` 非空时走命令回执（同 ID 重试重放结果，不重复执行）。
        """
        cid = str(command_id or "").strip()
        if not cid:
            return self._rollbackSubagentInner(subagent_id)
        from neurova.core.command_receipt import executeWithReceipt

        try:
            result, replayed = executeWithReceipt(
                _receiptConnection(),
                command_id=cid,
                command_type="rollback_subagent",
                thread_id=str(subagent_id or ""),
                fn=lambda: self._rollbackSubagentInner(subagent_id),
            )
        except Exception as exc:  # noqa: BLE001 - 回执三态错误如实转拒绝结构
            return _receiptRejection(exc)
        if replayed:
            result = dict(result or {})
            result["replayed"] = True
        return result

    def _rollbackSubagentInner(self, subagent_id: str) -> Dict[str, Any]:
        """rollbackSubagent 的无回执内层（同一命令的组成部分，不单独进回执）。"""
        sid = str(subagent_id or "").strip()
        if not sid:
            return {"success": False, "error": "subagent_id 不能为空"}
        with self._lock:
            run = self._runs.get(sid)
        if run is None:
            return {"success": False, "error": f"未找到子 Agent 运行记录: {sid}"}
        from neurova.agent.neuacp.adapter_surface import (
            CapabilityNotDeclared,
            NeuacpMemberSurface,
        )

        try:
            result = NeuacpMemberSurface.forRun(run).rollback()
        except CapabilityNotDeclared as exc:
            self._logRunEvent(run, "rollback_rejected", {
                "reason": str(exc)[:EVENT_ERROR_SUMMARY_CHARS]})
            return {"success": False, "error": str(exc)}
        self._logRunEvent(run, "rollback", {
            "success": bool((result or {}).get("success")),
            "restored_ref": str((result or {}).get("restored_ref") or ""),
            "pre_restore_ref": str((result or {}).get("pre_restore_ref") or ""),
        })
        return result

    async def updateSubagent(
        self,
        subagentId: str,
        message: str,
        mode: str = "steer",
        background: bool = False,
        session_id: Optional[str] = None,
        initiator_agent: Optional[Any] = None,
        command_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """改需求（A3 回执幂等包装）。

        ``command_id`` 非空时整段改需求走命令回执（同 ID 重试重放、不重复
        注入/重派）；空（缺省）保持原行为。restart 内部的二次续跑调用走
        inner，不再进回执（同一命令的组成部分，不是新命令）。
        """
        cid = str(command_id or "").strip()
        if not cid:
            return await self._updateSubagentInner(
                subagentId, message, mode=mode, background=background,
                session_id=session_id, initiator_agent=initiator_agent,
            )
        from neurova.core.command_receipt import executeWithReceiptAsync

        async def _afn() -> Dict[str, Any]:
            return await self._updateSubagentInner(
                subagentId, message, mode=mode, background=background,
                session_id=session_id, initiator_agent=initiator_agent,
            )

        try:
            result, replayed = await executeWithReceiptAsync(
                _receiptConnection(),
                command_id=cid,
                command_type="update_subagent",
                thread_id=str(session_id or subagentId or ""),
                afn=_afn,
            )
        except Exception as exc:  # noqa: BLE001 - 回执三态错误如实转拒绝结构
            return _receiptRejection(exc)
        if replayed:
            result = dict(result or {})
            result["replayed"] = True
        return result

    async def _updateSubagentInner(
        self,
        subagentId: str,
        message: str,
        *,
        mode: str = "steer",
        background: bool = False,
        session_id: Optional[str] = None,
        initiator_agent: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """改需求（interrupt|enqueue 双策略，对照批）。

        - 终态 run → 走既有续跑链（resumeFinishedRun：member 会话复用 + 溯源）；
        - 运行中 run：
          mode=steer（默认，尽力而为）→ 新指令注入成员会话插话队列，成员下一
            工具轮可见；若成员已不再调用工具则不会送达（如实提示，可改 restart）；
          mode=restart → 先叫停再按终态续跑链重派（resumed_from 溯源保留）。
        - C2 接线（G3 收敛面）：mode=fork → 经 NeuacpMemberSurface.fork 派生
            新分支 run（新 member 会话、resumed_from 溯源），原 run 不叫停不改动；
          mode=resume → 显式点名续跑（只针对终态 run，语义同缺省续跑链）。
        """
        sid = str(subagentId or "").strip()
        text = str(message or "").strip()
        if not sid:
            return {"success": False, "error": "subagent_id 不能为空"}
        if not text:
            return {"success": False, "error": "message 不能为空（新需求/修正指令）"}
        with self._lock:
            run = self._runs.get(sid)
        if run is None:
            return {"success": False, "error": f"未找到子 Agent 运行记录: {sid}"}
        # C2 接线：mode 字典扩容（steer/restart 既有 + resume/fork 新增）。
        # 未知 mode 结构化拒绝（不静默当 steer——那会把语义错误的调用悄悄放行）。
        if mode not in ("steer", "restart", "resume", "fork"):
            return {"success": False,
                    "error": f"mode 仅支持 steer/restart/resume/fork（收到: {mode}）"}
        if mode == "fork":
            # fork：经收敛面派生新分支 run（原 run 不叫停不改动，进行中任务
            # 不受影响）。能力闸在面内：外部成员未声明 fork →
            # CapabilityNotDeclared（诚实拒绝）；内部 agent（caps None）放行。
            from neurova.agent.neuacp.adapter_surface import (
                CapabilityNotDeclared,
                NeuacpMemberSurface,
            )

            # B2 多触发点：fork 派生前把原 run 的任务书+产出经上下文传递工件
            # 随分支任务投递（同续跑形态：登记/预算/inline 投递/事件留痕，
            # transfer type 用 fork 语义）。工件需要原 run 已终态的产出
            # （report）——运行中来源无产出可交接，fork 照常不带工件（不假装
            # 带了，与 surface.fork「不叫停不改动」既有约束一致）。工件构建
            # 失败诚实降级不阻断 fork：分支从新会话起步，缺工件如实留痕
            # （context_transfer_failed），不静默截断也不编造。
            forkTask = text
            if run.status in SUBAGENT_FINISHED_STATUSES:
                handoffText, handoffMeta = self._buildResumeHandoff(
                    run, transfer_type="fork", intro_label="分支衔接")
                if handoffText:
                    forkTask = f"{handoffText}\n\n[分支任务]\n{text}"
                # handoffMeta.get("failed") 时不阻断：fork 照常派生（失败原因
                # 已由 _buildResumeHandoff 落 context_transfer_failed 事件）。
            try:
                forkResult = await NeuacpMemberSurface.forRun(run).fork(
                    forkTask, background=background)
            except CapabilityNotDeclared as exc:
                self._logRunEvent(run, "fork_rejected", {
                    "reason": str(exc)[:EVENT_ERROR_SUMMARY_CHARS]})
                return {"success": False, "error": str(exc)}
            self._logRunEvent(run, "forked", {
                "branch_subagent_id": str((forkResult or {}).get("subagent_id") or ""),
                "message": text[:EVENT_TASK_SUMMARY_CHARS],
            })
            if (isinstance(forkResult, dict) and not forkResult.get("error")
                    and not forkResult.get("rejected")):
                forkResult = dict(forkResult)
                forkResult["forked_from"] = run.subagent_id
            return forkResult
        if mode == "resume" and run.status in SUBAGENT_ACTIVE_STATUSES:
            return {"success": False,
                    "error": f"子代理 {sid} 仍在运行（status={run.status}）——"
                             "mode=resume 只针对已终态的运行；运行中改需求请用 "
                             "mode=steer（注入会话）或 mode=restart（先叫停再重派）"}
        if run.status in SUBAGENT_ACTIVE_STATUSES:
            if mode == "restart":
                cancelResult = self._cancelRunInner(sid, reason="改需求重派（先叫停再重派）")
                if not cancelResult.get("success"):
                    return {"success": False,
                            "error": f"叫停失败：{cancelResult.get('error', '')}"}
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    with self._lock:
                        cur = self._runs.get(sid)
                    if cur is None or cur.status in SUBAGENT_FINISHED_STATUSES:
                        break
                    await asyncio.sleep(0.02)
                return await self._updateSubagentInner(
                    sid, message, mode="steer", background=background,
                    session_id=session_id, initiator_agent=initiator_agent)
            # G3 收敛面：steer 经 NeuacpMemberSurface（邮箱机制不依赖 agent 侧
            # 支持，面内不加能力闸；编排层禁止绕过面直写队列）。
            from neurova.agent.neuacp.adapter_surface import NeuacpMemberSurface

            delivered = NeuacpMemberSurface.forRun(run).steer(text)
            self._logRunEvent(run, "update_injected", {
                "mode": "steer", "delivered": bool(delivered), "message": text[:120],
            })
            if not delivered:
                return {"success": False,
                        "error": "插话队列已满，注入失败（可稍后重试或改用 mode=restart）"}
            return {"success": True, "subagent_id": sid, "delivered": "steer",
                    "hint": "新指令将在成员下一工具轮生效；若成员已不再调用工具，"
                            "本条不会送达——可用 mode=restart 先叫停再重派"}
        return await self.resumeFinishedRun(
            sid, message, session_id=session_id,
            initiator_agent=initiator_agent, background=background,
        )

    async def resumeFinishedRun(
        self,
        subagentId: str,
        message: str,
        session_id: Optional[str] = None,
        initiator_agent: Optional[Any] = None,
        background: bool = False,
    ) -> Dict[str, Any]:
        """续跑一条已终态（completed/failed）的子 Agent（工具清单 3.1-3 续）。

        终态子 Agent 复活语义：member 会话键按决策复用——子 Agent 上一段的
        对话历史由既有会话恢复机制带回，续跑不是从零重派；上一段的 report
        （失败时为部分交接件）附在续跑任务里作衔接上下文。治理闸（深度/广度/
        预算/冷却/并发/错峰）与全新派生走同一条 spawn 路径。

        D-B（provider 中途切换放开·按租户隔离）：
        - 租户红线先于一切：非 admin 跨租户（run 谱系租户 / 团队租户不匹配）
          与「未找到」同形拒绝（不泄露存在性）；admin 豁免但落审计事件；
        - 续跑方式由「spawn 时刻执行体快照 vs 名册现值」经
          decideProviderTransition 五结果决策：reuse / switch_model_in_session
          （复用 member 会话）、restart_and_resume / create_with_handoff
          （重开 member 会话、交接工件随行）、reject（诚实拒绝带指引）；
        - 快照缺失的存量 run 按同 executor 同模型处理（向后兼容）。
        """
        if not (subagentId or "").strip():
            return {"error": "subagent_id 不能为空"}
        if not (message or "").strip():
            return {"error": "message 不能为空——请带续跑指令"}
        with self._lock:
            old = self._runs.get(subagentId)
        if old is None:
            return {"error": f"未找到子 Agent 运行记录: {subagentId}"}
        # ── D-B 租户隔离红线（§6.4；先于终态判定——跨租户连状态都不许探）──
        # 目标租户 = run 谱系租户 + 目标 agent 配置租户（外部成员=团队租户）。
        # 非 admin 跨租户一律拒绝，应答与「未找到」同形（teams_api 404 同纪律，
        # 不泄露目标存在性）；admin 豁免但落审计事件（resume_cross_tenant_admin）。
        from neurova.core.identity_context import get_request_user_id

        initiatorTenant = self._currentTenantId()
        targetTenant = str(getattr(old, "tenant_id", "") or "default")
        teamTenant = self._teamTenantId(old.team_id)
        crossTenant = (
            targetTenant != initiatorTenant
            or (teamTenant is not None and teamTenant != initiatorTenant)
        )
        if crossTenant:
            if self._initiatorIsPlatformAdmin():
                self._logRunEvent(old, "resume_cross_tenant_admin", {
                    "initiator": str(get_request_user_id() or ""),
                    "initiator_tenant": initiatorTenant,
                    "target_tenant": targetTenant,
                    "team_tenant": teamTenant,
                })
                logger.warning(
                    "Swarm: admin 跨租户续跑豁免 run=%s initiator=%s@%s "
                    "target_tenant=%s team_tenant=%s",
                    old.subagent_id, get_request_user_id(), initiatorTenant,
                    targetTenant, teamTenant,
                )
            else:
                logger.warning(
                    "Swarm: 跨租户续跑被拒（§6.4）run=%s initiator=%s@%s "
                    "target_tenant=%s team_tenant=%s",
                    old.subagent_id, get_request_user_id(), initiatorTenant,
                    targetTenant, teamTenant,
                )
                return {"error": f"未找到子 Agent 运行记录: {subagentId}"}
        if old.status not in SUBAGENT_FINISHED_STATUSES:
            return {
                "error": f"子 Agent {subagentId} 仍在运行（status={old.status}）——"
                         "续跑只针对已终态的运行；进行中的请用 subagent_status 等待",
            }
        # ── D-B 五结果决策：spawn 时刻执行体快照 vs 名册现值 ─────────────
        # 快照在（新外部成员 run）：tool/model 现值比对得 same_executor /
        # model_changed，installed 取 which 浅探测，走 decideProviderTransition。
        # 快照缺（存量 run / 本仓 agent）：按同 executor 同模型处理（向后兼容，
        # C5 原判定——能力档既无 session_reuse 也无 resume 时诚实拒绝）。
        snapshotCaps = getattr(old, "executor_caps_snapshot", None)
        sameExecutor, modelChanged, targetInstalled = True, False, True
        currentTool, currentModel = "", ""
        decision = None
        # C2 接线（G3 收敛面）：会话内换模型分支经 surface.switchModel 判定，
        # 面内拒绝（能力未声明/决策 reject）时携带的诚实原因。
        switchError = ""
        if isinstance(snapshotCaps, dict) and snapshotCaps:
            current = self._resumeTargetProfile(old)
            if current is None:
                return {
                    "success": False,
                    "error": "续跑目标执行体档案已不可得（名册成员或 executor 已"
                             "移除/禁用）——请重派全新任务或恢复其 executor 配置",
                }
            currentTool = str(current.get("tool") or "")
            currentModel = str(current.get("model") or "")
            sameExecutor = currentTool == str(getattr(old, "executor_tool", "") or "")
            modelChanged = currentModel != str(getattr(old, "executor_model", "") or "")
            targetInstalled = bool(current.get("installed"))
            if sameExecutor and modelChanged:
                # C2 接线：切换分支改经 surface.switchModel 做能力闸 + 五结果
                # 决策（编排层禁止绕过面自判；外部成员未声明
                # model_switch_in_session → 面内 CapabilityNotDeclared，转既有
                # 结构化拒绝；决策语义与 decideProviderTransition 同一口径）。
                from neurova.agent.neuacp.adapter_surface import (
                    CapabilityNotDeclared,
                    NeuacpMemberSurface,
                )

                try:
                    switchVerdict = NeuacpMemberSurface.forRun(old).switchModel(
                        currentModel)
                except CapabilityNotDeclared as exc:
                    decision, switchError = "reject", str(exc)
                else:
                    decision = switchVerdict.get("decision") or "reject"
                    if not switchVerdict.get("success"):
                        switchError = str(switchVerdict.get("error") or "")
            else:
                from neurova.agent.neuacp.catalog import decideProviderTransition

                decision = decideProviderTransition(
                    snapshotCaps, current.get("caps") or {},
                    same_executor=sameExecutor, target_installed=targetInstalled,
                    model_changed=modelChanged,
                )
        else:
            memberCaps = self._memberExecutorCaps(old)
            if memberCaps is not None:
                from neurova.agent.neuacp.catalog import decideProviderTransition

                decision = decideProviderTransition(
                    memberCaps, memberCaps,
                    same_executor=True, target_installed=True, model_changed=False,
                )
        # 决策事件（D-B 增补 same_executor/model_changed/tenant_checked 键；
        # decision 键维持原名，向后兼容）
        self._logRunEvent(old, "resume_decision", {
            "decision": decision,
            "same_executor": sameExecutor,
            "model_changed": modelChanged,
            "tenant_checked": True,
        })
        if switchError:
            # C2：面内拒绝（能力未声明/请求模型不一致/目标不可用）——诚实原因
            # 已由收敛面给出，这里原样透出（不另造第二份拒绝文案）。
            return {"success": False, "error": switchError}
        if decision == "reject":
            return {
                "success": False,
                "error": self._resumeRejectReason(
                    old, sameExecutor=sameExecutor, modelChanged=modelChanged,
                    targetInstalled=targetInstalled, currentTool=currentTool,
                    currentModel=currentModel),
            }

        # B2（参照系 ac 借鉴）：续跑衔接升级为上下文传递工件（登记/预算/省略
        # 可恢复/inline 投递/事件留痕），替代旧的 report[:4000] 裸截断。
        task = message.strip()
        # G3 收敛面：交接工件构建经 NeuacpMemberSurface（跨 executor 时在面内
        # 按既有五结果判定同口径要求 handoff_inject；工件本体仍复用
        # _buildResumeHandoff 单一实现，编排层禁止绕过面直建）。
        from neurova.agent.neuacp.adapter_surface import NeuacpMemberSurface

        handoffText, handoffMeta = NeuacpMemberSurface.forRun(old).handoffArtifact(message)
        if handoffText:
            task = f"{handoffText}\n\n[续跑指令]\n{task}"
        elif handoffMeta.get("failed"):
            # 诚实降级：交接工件构建失败（如预算不足）不静默截断——旧产出仍可
            # 经 member 会话恢复机制带回，但本次续跑如实标注未带衔接工件。
            return {
                "success": False,
                "error": f"上下文交接工件构建失败：{handoffMeta.get('reason', '')}"
                         "（可调大 NEUROVA_CONTEXT_HANDOFF_TOKEN_CAP 后重试；"
                         "旧产出仍可经成员会话历史 recall）",
            }
        # D-B 落地：reuse / switch_model_in_session 复用 member 会话（历史由
        # 既有会话恢复带回；后者换模型发生在同一会话内）；restart_and_resume /
        # create_with_handoff 重开 member 会话（旧产出经上方交接工件随行，
        # resumed_from 溯源保留）；decision None（本仓 agent / 无名册）维持原样复用。
        reuseSession = decision is None or decision in ("reuse", "switch_model_in_session")
        # 团队谱系随行：team_id 原样回传并显式点名原成员（不重走自动选人——
        # 旧「team_id 不随行」的顾虑由点名化解；外部成员由此解析到名册现值
        # 执行体，正是 D-B 中途切换的落点）。
        teamOverride = None
        if old.team_id:
            teamOverride = (dict(old.team_member) if old.team_member
                            else self._rosterMemberOverride(old.team_id, old.agent_id))
        result = await self.spawn(
            task,
            agent_id=old.agent_id,
            session_id=session_id if session_id is not None else old.session_id,
            background=background,
            origin="chat",
            stream=True,
            initiator_agent=initiator_agent,
            subagent_type=old.subagent_type,
            reuse_member_session_id=old.member_session_id if reuseSession else None,
            resumed_from=old.subagent_id,
            # S12：续跑是同一条协作的延续，project/room 归属标随行（档案才不断链）；
            # team_id 随行 + 点名原成员（D-B：外部成员续跑须重解析名册现值执行体）。
            room_id=old.room_id or None,
            project_id=old.project_id or None,
            team_id=old.team_id or None,
            team_role=old.team_role or None,
            teamMemberOverride=teamOverride,
        )
        if isinstance(result, dict) and not result.get("error") and not result.get("rejected"):
            result["provider_transition"] = decision
        return result

    def _memberExecutorCaps(self, run: SubAgentRun) -> Optional[Dict[str, Any]]:
        """外部成员的执行体能力档（C5 消费点）；本仓 agent / 无名册 → None。

        能力档只来自 neuacp 目录声明（单一事实源）：按 run.team_id 查名册、
        按 agent_id 对位成员，取其 executor.tool 的目录声明。查询失败一律
        None（不设限，不因名册读故障阻断续跑）。
        """
        profile = self._executorProfileFor(run.agent_id, run.team_id)
        return profile["caps"] if profile else None

    def _executorProfileFor(self, agentId: Optional[str],
                            teamId: Optional[str]) -> Optional[Dict[str, Any]]:
        """外部成员执行体档案单源（D-B）：{"tool", "caps"}；不可得 → None。

        能力档只来自 neuacp 目录声明（单一事实源）：按 team_id 查名册、按
        agent_id 对位成员，取其 executor.tool 与目录能力档出口拷贝。查询失败
        一律 None——调用方按各自语义处置（spawn 不落快照、续跑 fail-closed）。
        """
        try:
            if not agentId or not teamId:
                return None
            from neurova.agent.neuacp.catalog import capabilitiesFor
            from neurova.api.endpoints.teams_api import getTeamRoster

            roster = getTeamRoster(str(teamId))
            for member in (roster or {}).get("members_detail") or []:
                if str(member.get("user_id") or "") != str(agentId):
                    continue
                spec = member.get("executor")
                if not isinstance(spec, dict) or not str(spec.get("tool") or "").strip():
                    return None
                tool = str(spec.get("tool"))
                return {"tool": tool, "caps": capabilitiesFor(tool)}
        except Exception as exc:  # noqa: BLE001 - 名册/目录读故障不阻断主链
            logger.debug("成员执行体档案读取失败: %s", exc)
            return None
        return None

    def _resumeTargetProfile(self, run: SubAgentRun) -> Optional[Dict[str, Any]]:
        """续跑时刻的目标执行体档案（D-B）：{tool, caps, model, installed}。

        与 spawn 时刻快照（executor_caps_snapshot/executor_tool/executor_model）
        同口径：tool/caps 取名册现值（_executorProfileFor 单源），model 经既有
        解析链从当前执行体适配器读数，installed 取 which 浅探测。名册不可得
        → None（调用方 fail-closed 拒绝，不猜）。
        """
        profile = self._executorProfileFor(run.agent_id, run.team_id)
        if profile is None:
            return None
        tool = profile["tool"]
        try:
            from neurova.agent.neuacp.catalog import probeToolHealth

            installed = bool(probeToolHealth(tool, deep=False).get("installed"))
        except Exception:  # noqa: BLE001 - 探测故障按未安装处理（fail-closed）
            installed = False
        model = ""
        try:
            adapter, _error = self._resolveExternalMember(run.agent_id, run.team_id)
            if adapter is not None:
                model = self._resolve_model_name(adapter) or ""
        except Exception as exc:  # noqa: BLE001 - 模型读数失败按空串比较（不阻断决策）
            logger.debug("续跑目标模型名读取失败（按空串比较）: %s", exc)
        return {"tool": tool, "caps": profile["caps"], "model": model,
                "installed": installed}

    def _rosterMemberOverride(self, teamId: str, agentId: str) -> Optional[Dict[str, Any]]:
        """从名册现值构造 teamMemberOverride（续跑点名原成员，不重走自动选人）。

        旧续跑「team_id 不随行」是怕重走选人改变续跑语义；显式点名同名成员后
        team_id 可安全随行——外部成员由此重新解析到名册现值执行体（D-B 中途
        切换的落点）。成员已不在名册 → None（spawn 侧按各自闸门诚实处置）。
        """
        try:
            from neurova.api.endpoints.teams_api import getTeamRoster

            roster = getTeamRoster(str(teamId)) or {}
            for member in (roster.get("members_detail") or []):
                if str(member.get("user_id") or "") == str(agentId or ""):
                    return {
                        "user_id": str(member.get("user_id") or ""),
                        "name": str(member.get("name") or ""),
                        "role": str(member.get("role") or "member"),
                        "prompt": str(member.get("prompt") or ""),
                    }
        except Exception as exc:  # noqa: BLE001 - 名册读故障回退 None
            logger.debug("续跑点名成员读取失败: %s", exc)
        return None

    def _teamTenantId(self, teamId: Optional[str]) -> Optional[str]:
        """团队租户（部门根，§6.4）；无团队 / 读失败 → None（只按 run 租户判定）。"""
        tid = str(teamId or "").strip()
        if not tid:
            return None
        try:
            from neurova.api.endpoints.teams_api import getTeamRoster

            team = getTeamRoster(tid) or {}
            return str(team.get("tenant_id") or "default")
        except Exception:  # noqa: BLE001 - 读失败不猜租户，交由 run 租户判定
            return None

    def _initiatorIsPlatformAdmin(self) -> bool:
        """当前请求者是否平台 admin（users 表 role 单源；fail-closed 非 admin）。

        判定复用 approval_chain._deciderIsPlatformAdmin（同包既有实现，同读
        users 表 role 列；其模块未列本卡白名单不许改导出，故经惰性 import
        复用，不另写第二份 users 表判定）。
        """
        try:
            from neurova.core.identity_context import get_request_user_id

            userId = str(get_request_user_id() or "").strip()
            if not userId:
                return False
            from neurova.agent.approval_chain import _deciderIsPlatformAdmin

            return bool(_deciderIsPlatformAdmin(userId))
        except Exception:  # noqa: BLE001 - 判定失败按非 admin（fail-closed）
            return False

    def _resumeRejectReason(self, run: SubAgentRun, *, sameExecutor: bool,
                            modelChanged: bool, targetInstalled: bool,
                            currentTool: str, currentModel: str) -> str:
        """续跑被拒的诚实原因（D-B）：点名挡在哪个判定分支，并给下一步指引。"""
        snapshotTool = str(getattr(run, "executor_tool", "") or "")
        snapshotModel = str(getattr(run, "executor_model", "") or "")
        if not targetInstalled:
            return (f"目标执行体 {currentTool or '(未知)'} 当前未安装或不可用"
                    "（which 探测未命中）——请安装后重试、改派其他成员或重派全新任务")
        if not sameExecutor:
            return (f"执行体已从 {snapshotTool or '(未知)'} 切换为 "
                    f"{currentTool or '(未知)'}，且双方能力档未同时声明 "
                    "handoff_inject——不支持跨执行体交接续跑；请恢复原 executor "
                    "配置或重派全新任务")
        if modelChanged:
            return (f"模型已从 {snapshotModel or '(空)'} 变更为 "
                    f"{currentModel or '(空)'}，目标执行体能力档未声明 "
                    "model_switch_in_session——保守拒绝会话内换模型；请恢复原模型 "
                    "配置或重派全新任务")
        return ("该外部成员执行体能力档不支持续跑（无 session_reuse/resume 声明）"
                "——请重派全新任务或调整其 executor 配置")

    def _buildResumeHandoff(self, old: SubAgentRun, *, transfer_type: str = "subagent_result",
                            intro_label: str = "续跑衔接") -> tuple:
        """B2（参照系 ac 借鉴）：续跑/分支衔接升级为上下文传递工件。

        旧任务书 + 旧产出（report）作为两条历史条目，按预算物化 ContextHandoff
        并 inline 投递（替代旧 report[:4000] 裸截断——预算内完整衔接，省略
        如实记录）。返回 (inline_text, meta)；meta.failed=True 表示构建失败
        （预算不足等），调用方诚实降级（不静默截断）。report 为空 → ("", {})。
        事件留痕：context_transfer / context_transfer_failed 入 H-4 账本。

        transfer_type：登记的传递类型（续跑衔接=subagent_result 缺省；
        fork 分支衔接传 "fork"）。intro_label：任务书前缀的用途标注。
        """
        report = str(getattr(old, "report", "") or "").strip()
        oldTask = str(getattr(old, "task", "") or "").strip()
        if not report:
            return "", {}
        from neurova.agent.context_transfer import (
            ContextHandoffBudgetError,
            ContextSourcePoint,
            ContextTransfer,
            ContextTransferError,
            buildHandoff,
            markDelivery,
            renderInlinePrefix,
        )

        transfer = ContextTransfer(
            transfer_id=f"tr_{uuid.uuid4().hex[:12]}",
            type=transfer_type,
            source_point=ContextSourcePoint(
                thread_id=str(old.member_session_id or old.subagent_id or ""),
                run_id=str(old.subagent_id or ""),
            ),
        )
        items: List[Dict[str, Any]] = []
        if oldTask:
            items.append({
                "id": f"{old.subagent_id}:task", "role": "user", "content": oldTask,
            })
        items.append({
            "id": f"{old.subagent_id}:report", "role": "assistant", "content": report,
        })
        stateLabel = "失败前部分" if old.status == SUBAGENT_FAILED else "已完成部分"
        tokenCap = _handoffTokenCap()
        try:
            handoff = buildHandoff(
                transfer,
                thread_id=str(old.member_session_id or old.subagent_id or ""),
                target_run_id=None,
                strategy="delta_since_last_seen",
                items=items,
                token_cap=tokenCap,
                window_tokens=tokenCap,
            )
            prefix = renderInlinePrefix(handoff)
            markDelivery(handoff, "inline")
        except (ContextHandoffBudgetError, ContextTransferError) as exc:
            self._logRunEvent(old, "context_transfer_failed", {
                "reason": str(exc), "report_chars": len(report),
                "token_cap": tokenCap,
            })
            return "", {"failed": True, "reason": str(exc)}
        self._logRunEvent(old, "context_transfer", {
            "transfer_id": transfer.transfer_id,
            "handoff_id": handoff.handoff_id,
            "type": transfer.type,
            "strategy": handoff.strategy,
            "delivery": handoff.delivery_status,
            "omitted_item_ids": list(handoff.omitted_item_ids),
            "budget_tokens": handoff.budget_tokens,
            "budget_bytes": handoff.budget_bytes,
        })
        return (
            f"[{intro_label}] 这是上一次执行的产出（{stateLabel}），"
            f"供你衔接，不要从头重复：\n{prefix}"
        ), {
            "handoff_id": handoff.handoff_id,
            "transfer_id": transfer.transfer_id,
            "omitted": list(handoff.omitted_item_ids),
        }

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

    # ── 外部编码代理成员（neuacp，设计文档 §4.2/§6.4） ─────────────

    def _externalAgentsEnabled(self) -> bool:
        raw = (os.environ.get("NEUROVA_EXTERNAL_AGENTS_ENABLED") or "").strip().lower()
        return raw in ("on", "1", "true", "yes")

    def _currentTenantId(self) -> str:
        """发起者租户（JWT 部门根，§6.4）；单源在 user_group_model.currentUserTenantId。"""
        from neurova.auth.user_group_model import currentUserTenantId

        return currentUserTenantId()

    def _resolveExternalMember(self, agent_id: Optional[str], team_id: Optional[str]) -> tuple:
        """名册成员带 executor 标记时构造外部成员适配器。

        Returns:
            (NeuacpMemberAdapter 或 None, 拒绝原因或 None)
            - 成员不存在 / 未配 executor → (None, None)：走内置解析路径。
            - 开关关闭 / 跨租户 / 配置缺失 → (None, 拒绝原因)：spawn 侧结构化拒绝。
        """
        if not agent_id or not team_id:
            return None, None
        try:
            from neurova.api.endpoints.teams_api import getTeamRoster

            team = getTeamRoster(team_id)
        except Exception:
            return None, None
        if not isinstance(team, dict):
            return None, None
        member = None
        for item in (team.get("members_detail") or []):
            if str(item.get("user_id")) == str(agent_id):
                member = item
                break
        if member is None:
            return None, None
        spec = member.get("executor")
        if not isinstance(spec, dict) or not spec:
            return None, None
        if not self._externalAgentsEnabled():
            return None, (
                "外部代理接入未启用（NEUROVA_EXTERNAL_AGENTS_ENABLED=off）——"
                f"名册成员 {agent_id} 配置了外部执行体，无法派活"
            )
        initiator_tenant = self._currentTenantId()
        team_tenant = str(team.get("tenant_id") or "default")
        if initiator_tenant != team_tenant:
            # D-B：平台 admin 豁免跨租户限制（users 表 role 单源判定，留审计
            # 日志）——续跑链的租户闸已先行拦截/放行并留痕，这里豁免才能让
            # admin 的跨租户续跑在派生闸不二次死锁；非 admin 维持 §6.4 红线。
            if self._initiatorIsPlatformAdmin():
                logger.warning(
                    "Swarm: 跨租户派活 admin 豁免 team=%s initiator_tenant=%s "
                    "team_tenant=%s", team_id, initiator_tenant, team_tenant)
            else:
                return None, (
                    f"跨租户派活被拒：发起者租户 {initiator_tenant!r} != "
                    f"团队租户 {team_tenant!r}（§6.4 租户隔离红线）"
                )
        # F1 第二闸（拍板 D-D，设计文档 §3.1）：租户闸之后、提取 kind/构造执行体
        # 之前——名册经旧数据/旁路写入的不支持组合在这里 fail-closed，
        # 「refused before anything opens」，绝不为其开进程。
        from neurova.agent.neuacp.catalog import protocolVersionFor, refuseExecutorSpec

        capabilityReasons = refuseExecutorSpec(spec)
        if capabilityReasons:
            return None, (
                f"外部成员 {agent_id} 能力不支持：{'；'.join(capabilityReasons)}"
            )
        kind = str(spec.get("kind", "acp"))
        command = [str(part) for part in (spec.get("command") or [])]
        if not command:
            return None, f"外部成员 {agent_id} 缺少启动命令（executor.command）"
        cwd = str(spec.get("cwd") or "")
        # C1（§4.8）：名册 transport/remote 透传——remote.key_ref 只透引用名，
        # 私钥路径由 ssh_transport 在 spawn 期经 key_resolver 从环境解析。
        transport = str(spec.get("transport") or "stdio")
        remote = spec.get("remote") if isinstance(spec.get("remote"), dict) else None
        name = str(member.get("name") or agent_id)
        try:
            from neurova.agent.neuacp import NeuacpError

            if kind == "acp":
                from neurova.agent.neuacp import NeuacpMemberAdapter, NeuacpStdioExecutor
                from neurova.agent.neuacp.ssh_transport import applyRemoteTransport

                # G1：按目录条目声明的 ACP 协议版本创建执行体（registry 声明
                # v2 的 agent 经 client.start(protocol_version=...) 协商；
                # 预设/未声明缺省 "1"，行为不变）。
                executor = NeuacpStdioExecutor(
                    command, cwd=cwd,
                    protocol_version=protocolVersionFor(str(spec.get("tool") or "")),
                    run_tenant_id=team_tenant,
                )
                applyRemoteTransport(executor, transport, remote)
                # P1 移交清偿：spawn 装配接入进程池（键含租户段，§6.4）；
                # 池故障 fail-open——acquire 失败在 executor.start 内退回直启。
                self._attachExternalProcessPool(executor, spec, team_tenant, command, cwd)
            elif kind == "plugin":
                from neurova.agent.neuacp import NeuacpMemberAdapter, NeuacpPluginExecutor

                executor = NeuacpPluginExecutor(command, cwd=cwd, transport=transport, remote=remote,
                                                 run_tenant_id=team_tenant)
            else:
                return None, f"外部成员 {agent_id} 的执行体类型未知：{kind!r}"
        except ImportError:
            return None, f"外部成员 {agent_id} 的插件执行体尚未可用（kind=plugin 待 A8 落地）"
        except NeuacpError as exc:
            return None, f"外部成员 {agent_id} 的传输配置无效：{exc}"
        return NeuacpMemberAdapter(executor, name=name, cwd=cwd), None

    def _attachExternalProcessPool(self, executor: Any, spec: dict, tenant: str,
                                   command: List[str], cwd: str) -> None:
        """给 ACP 执行体挂进程池（NeuacpProcessPool，进程级单例）。

        池键 ``(tenant, tool, command, cwd, transport, remote)``——租户段固定
        首位（§6.4 跨租户不共享进程）；remote 连接参数确定性序列化进键段。
        挂载失败只降级为直启（fail-open），不阻断派活。
        """
        try:
            from neurova.agent.neuacp.process_pool import getNeuacpProcessPool, poolKey

            remote = spec.get("remote")
            if isinstance(remote, dict):
                remoteSeg = json.dumps(remote, sort_keys=True, ensure_ascii=False)
            else:
                remoteSeg = str(remote or "")
            key = poolKey(
                tenant,
                str(spec.get("tool") or ""),
                [str(part) for part in (command or [])],
                str(cwd or ""),
                str(spec.get("transport") or "stdio"),
                remoteSeg,
            )
            executor.attachProcessPool(getNeuacpProcessPool(), key)
        except Exception as exc:  # noqa: BLE001 - fail-open：池不可用则直启
            logger.warning("外部进程池接入失败，执行体退回直启 (tool=%s): %s",
                           spec.get("tool"), exc)

    def _releaseExternalAdapter(self, adapter: Any) -> None:
        """run 终态后释放外部成员适配器（executor.close）。

        池接入时 close=release（进程回池待复用，秒级记账）；直启时
        close=terminate（可能秒级阻塞）——统一放后台任务执行，不阻塞终态
        广播；强引用集合防任务被 GC 吞掉。适配器无 close（替身对象）时跳过。
        """
        closeAdapter = getattr(adapter, "close", None)
        if not callable(closeAdapter):
            return
        try:
            task = asyncio.create_task(closeAdapter())
        except RuntimeError:
            # 无运行中事件循环（罕见）：池路径由空闲回收兜底，直启路径随进程退出收尾
            logger.debug("外部适配器释放无可用事件循环 (adapter=%s)", getattr(adapter, "config", None))
            return
        self._adapterCloseTasks.add(task)
        task.add_done_callback(self._adapterCloseTasks.discard)


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
            self._logRunEvent(run, "stalled", {
                "stalled_seconds": payload["stalled_seconds"],
                "reminder_count": payload["reminder_count"],
            })
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

    @staticmethod
    def _subagentAccountingUserId(initiator_agent: Any) -> str:
        """子代理记账身份：**agent 属主优先**（§3 裁定——运行台账行 user_id
        与续跑权威按属主，可见性同口径）；属主缺省才退发送者直读转发，再退
        空串。旧形发送者优先会在 admin/他人代跑时把台账行记到点击者名下，
        属主反而看不见自己的 run（台账自家注释：跟着点击者走＝接线顺手造
        出来的越权面）。fullrepo 审计 2026-11-18 B2/G3 收口。
        """
        return str(getattr(initiator_agent, "owner_user_id", "")
                   or getattr(initiator_agent, "current_user_id", "") or "")

    @staticmethod
    def _bindMemberCostContext(agentId: str, memberSessionId: str, traceId: str) -> dict:
        """member 成本上下文绑定：把 cost_tracking 的调用上下文覆写为 member
        归属（agent_id=member），返回**前值**供 finally 还原——member 结束后
        父代同任务内的后续 LLM 调用不被误记到 member 名下。读取侧见
        multi_model_client._usageAgentId（fullrepo 审计 2026-11-18 C1 收尾）。
        """
        from neurova.models.cost_tracking import get_llm_cost_context, set_llm_cost_context

        prev = get_llm_cost_context()
        set_llm_cost_context(agent_id=agentId, session_id=memberSessionId, turn_id=traceId)
        return prev

    @staticmethod
    def _restoreCostContext(prev: dict) -> None:
        """按 `_bindMemberCostContext` 返回的前值还原成本上下文。"""
        from neurova.models.cost_tracking import set_llm_cost_context

        set_llm_cost_context(
            agent_id=prev.get("agent_id"),
            session_id=prev.get("session_id"),
            turn_id=prev.get("turn_id"),
        )

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
        transitionRun(run, SUBAGENT_RUNNING, cause="member_started")
        # B4：开跑即出队（队列只持排队中的 run；软出队，不在队不抛）
        _runQueue().dequeue(run.subagent_id)
        # P3-2（评测报告 G-12）：member 轨迹 trace——spawn→member→回流共一条可查询
        # 的 span 树；fail-open（轨迹故障/开关关闭不阻断子任务，与台账同口径）。
        userId = self._subagentAccountingUserId(initiator_agent)
        # C1 收尾：member 的 LLM 用量归因到 member agent（覆写父轮上下文，
        # finally 按前值还原）——读取侧 multi_model_client._usageAgentId。
        prevCostCtx = self._bindMemberCostContext(
            run.agent_id, run.member_session_id, run.trace_id)
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
            projectId=run.project_id,
            teamId=run.team_id,
            # F5：spawn 时刻单源——吃 run.tenant_id，运行中不再重读租户
            tenantId=run.tenant_id,
        )
        # F5：谱系现算一次，subagent_started 载荷与 spawn_metadata 共用
        runLineage = self._runLineage(run)
        # H-4：started 事件入账（因果链接在 spawned 之后）
        self._logRunEvent(run, "started", {
            "status": run.status, "model": run.model, "trace_id": run.trace_id,
        })
        # B1/B2：外部编码代理成员（NeuacpMemberAdapter）在 chat 前绑定运行上下文
        # ——permission 桥接审批链、tool_call 镜像进账本与 span 轨迹都以此为锚。
        # 内置 Agent 无此方法，getattr 鸭子判定，零影响。
        bindRun = getattr(agent, "bindRun", None)
        if callable(bindRun):
            try:
                bindRun(run, self._logRunEvent, recorder=recorder, spanId=memberSpanId)
            except Exception as e:  # noqa: BLE001 - 绑定失败不阻断派生（外部成员按未绑定态 fail-closed）
                logger.warning("Swarm: 外部成员 bindRun 失败 (%s): %s", run.subagent_id, e)
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
                # S10：团队溯源标（前端 SubAgentPanel 团队徽标）
                "team_id": run.team_id,
                "team_role": run.team_role,
                # F5：租户与谱系随事件透出（前端可选消费，不强制适配）
                "tenant_id": run.tenant_id,
                "parent_subagent_id": run.parent_subagent_id,
                "agent_path": runLineage["agent_path"],
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
        # F5 谱系：把本 run 的 id 绑进上下文——member 内 spawn_subagent 递归
        # 派生时，子代 spawn 路径据此读出 parent_subagent_id（父链单源）。
        subagentIdToken = setCurrentSubagentId(run.subagent_id)
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
                # F5：帧谱系——执行体经 ctx.metadata 取用作帧账本 lineage
                "lineage": runLineage,
            }
            # S9 共享黑板：run 关联协作房间时，member 轮记忆按 room:<room_id> 作用域
            # 打标/召回（写读两侧经 memory_scope 的显式 chat_scope 透传，同构继承
            # room 语义——群群隔离、读单聊基线），不新造作用域体系。
            scopeTag = memberChatScope(run)
            if scopeTag:
                spawn_metadata["chat_scope"] = scopeTag
            if emitter is not None:
                spawn_metadata["event_emitter"] = emitter
            # stream=True（2026-09-10 蜂群超时排查）：非流式的读超时是"整段
            # 生成总窗口"，思考型子 agent 生成整份报告超窗即 ReadTimeout；
            # 流式按字节间隙计且静默看门狗/小窗实时流（SUBAGENT_CHUNK）全部依赖它
            #
            # K 条根修：流式把"整段总窗口"交给了调用方，而 `multi_model_client` 的
            # 静默看门狗**只留 WARNING 不中止**——上游停滞死流时这条 run 永久停在
            # running，既逐不出去也永远占着派生槽。故在此加一条与工具层同源的总闸。
            # S10/S11：发起人显式给的 run 级预算（runtime_budget_sec>0）优先于默认读数。
            budget = run.runtime_budget_sec if run.runtime_budget_sec > 0 else self._effectiveRuntimeBudget()
            # P1-1：member 实际收到的是"原始任务描述 + 结构化任务书"拼装提示词；
            # 台账/事件里的 run.task 保持原始文本不混排。
            memberPrompt = renderTaskUnitPrompt(run.task, run.task_unit)

            # 任务驱动回忆（14 号设计稿落地批）：派活时按任务书关键词召回
            # 经验/教训/技能/偏好注入任务提示词（proactive_recall.enabled
            # 总开关；fail-soft，不阻断派活主链）。
            try:
                from neurova.cognitive_layers.memory_layer.proactive_recall import (
                    renderTaskRecallSection,
                    taskDrivenRecall,
                )

                taskRecall = taskDrivenRecall(
                    getattr(agent, "memory_manager", None), str(run.task or ""), limitPerCategory=3
                )
                recallSection = renderTaskRecallSection(taskRecall)
                if recallSection:
                    memberPrompt = f"{memberPrompt}\n\n{recallSection}"
            except Exception as recallError:  # noqa: BLE001 — 召回失败按原任务书派活
                logger.debug("任务驱动回忆跳过: %s", recallError)

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
            # S4 结果候选制：member 结果回传**先落候选**（submitted），不直接定案；
            # 验收/评审通过后由主侧经审批链 + CAS 合入，冲突保留升级人工裁决。
            candidate = self._submitResultCandidate(run, report)
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
                self._rejectCandidateForRun(run, candidate, gate.failedReason)
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
                self._rejectCandidateForRun(run, candidate, review.failedReason)
                run.cause = review.cause
                raise RuntimeError(review.failedReason)
            report = review.report
            # 终稿回填候选（回炉/评审修正后的完整产出），再走主侧审批 + CAS 合入
            candidate = self._candidates.resubmitCandidate(candidate.candidateId, report)
            mergeOutcome = await self._mergeCandidateForRun(run, candidate)
            if not mergeOutcome.get("merged"):
                run.cause = mergeOutcome.get("cause") or "merge_failed"
                raise RuntimeError(str(mergeOutcome.get("error") or "结果合入未完成"))
            run.report = candidate.content
            transitionRun(run, SUBAGENT_COMPLETED, cause="candidate_merged")
            run.finished_at = time.time()
        except asyncio.CancelledError:
            # 取消不是「没发生」：`CancelledError` 继承 `BaseException`，改前那一条
            # `except Exception` 抓不到它——run 就永久停在 running，槽位被占死（K 条）。
            # 现写终态、释放槽位，然后**照常上抛**：吞掉取消既是教义第 2 条的禁物，
            # 也会让 asyncio 的取消语义失真（外层以为没被取消）。
            transitionRun(run, SUBAGENT_FAILED, cause=SUBAGENT_CAUSE_CANCELLED)
            run.cause = SUBAGENT_CAUSE_CANCELLED
            _cancelNote = getattr(run, "cancel_note", "") or "父任务被取消"
            run.error = (f"subagent_cancelled（{_cancelNote}；子任务未跑完；"
                         "派生槽已释放，可直接重派）")
            run.report = self._partialHandback(contentBuffer)
            run.finished_at = time.time()
            raise
        except Exception as e:  # noqa: BLE001 - 子 Agent 故障隔离
            logger.warning("Swarm: 子 Agent %s 执行失败: %s", run.subagent_id, e)
            transitionRun(run, SUBAGENT_FAILED, cause=run.cause or "execution_failed")
            run.error = str(e)
            run.report = self._partialHandback(contentBuffer)
            run.finished_at = time.time()
        finally:
            # 台账终态与蜂群终态同一个落点：`completed`/`failed`/超时/取消都从这里收尾，
            # 缺一条就在台账里留一行永久 running 的幽灵（L 条的另一副面孔）。
            closeSubagentRun(ledgerRunId, run.status, run.cause)
            # H-4：终态事件入账（成败/超时/取消都从这里落，不留幽灵）；
            # error 摘要随行（cause 为空时它是唯一起因线索；截断防正文进账本）
            self._logRunEvent(run, "terminal", {
                "status": run.status, "cause": run.cause,
                "terminal_quality": getattr(run, "terminal_quality", ""),
                "error": (run.error or "")[:EVENT_ERROR_SUMMARY_CHARS],
                "duration_ms": round(run.duration * 1000, 3),
            })
            # B1：本 run 作为父 run 终结时，对其名下未销账的子结果投递单补投一次
            #（子结果到时父已收工的静默丢失口子在此收口）。
            try:
                self._deliveryCatchUp(run.subagent_id)
            except Exception as e:  # noqa: BLE001 - 补投失败不阻断终态收尾
                logger.debug("Swarm: 投递补扫失败 (%s): %s", run.subagent_id, e)
            # B4：终态即出队（队列只持排队中的 run；软出队，不在队不抛）。
            _runQueue().dequeue(run.subagent_id)
            self._endMemberTrace(recorder, memberSpanId, run)
            reset_subagent_depth(depth_token)
            resetCurrentSubagentId(subagentIdToken)
            set_subagent_tool_allowlist(None)
            self._restoreCostContext(prevCostCtx)
            # B3：run 已终态，外部成员适配器登记随之摘除（防跨 run 复用/泄漏）。
            with self._lock:
                registeredAdapter = self._externalAdapters.pop(run.subagent_id, None)
            # P1 移交清偿：终态即释放外部执行体——池接入时 release 归还进程
            # 待复用，直启时 terminate 收尾；不释放会让池名额只增不减（4 个
            # run 后永久排队）。
            if registeredAdapter is not None:
                self._releaseExternalAdapter(registeredAdapter[0])

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
                # S10：团队溯源标（前端 SubAgentPanel 团队徽标）
                "team_id": run.team_id,
                "team_role": run.team_role,
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
            # F2（设计文档 §3.2，断点 4）：chunk 元数据同步入 H-4 账本——只记
            # 类型与长度不记正文（H-4 纪律不变），chunk 与 tool_call/permission/
            # terminal 同账本同 seq，先后可判定；fail-open 由 _logRunEvent 兜住。
            self._logRunEvent(run, "member_chunk", {
                "chunk_type": event_type,
                "length": len(data) if isinstance(data, str) else 0,
            })
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
                SYSTEM_ACTOR_SWARM,
                get_session_sync_manager,
            )

            mgr = get_session_sync_manager()
            mgr.register_or_create_session(session_id=run.session_id, user_id=SYSTEM_ACTOR_SWARM)
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
            # A1：终态可信度分级随信封上行——父侧/验收门据此决定是否需要复核
            "terminal_quality": getattr(run, "terminal_quality", ""),
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

    def _registerRunQueue(self, run: SubAgentRun) -> None:
        """B4：run 入排队管理面（与 spawned 事件同点登记；fail-open 不阻断派生）。"""
        try:
            _runQueue().enqueue(run.subagent_id, run.task)
        except Exception as e:  # noqa: BLE001 - 队列登记失败不阻断派生主流程
            logger.debug("Swarm: 队列登记失败 (%s): %s", run.subagent_id, e)

    def runQueueSnapshot(self) -> List[Dict[str, Any]]:
        """排队 run 有序快照（B4 管理面读数：优先级降序+同级先来先服务，位次从 1 起）。"""
        return _runQueue().snapshot()

    def setRunQueuePriority(self, subagent_id: str, priority: str) -> int:
        """调整排队 run 的优先级（B4），返回调整后的新位次；不在队显式 KeyError。"""
        return _runQueue().setPriority(subagent_id, priority)

    def cancelQueuedRun(self, subagent_id: str) -> Dict[str, Any]:
        """取消排队 run（B4）：出队留痕 + run 判 failed（cause=subagent_cancelled）。

        仅对仍在队列中的 run 生效（不在队 KeyError）；已开跑/终态的 run 不在
        队列，走既有 cancelRun 通道。取消是诚实终态：落 status_changed/terminal
        事件与台账口径一致。
        """
        entry = _runQueue().cancelQueued(subagent_id)
        with self._lock:
            run = self._runs.get(subagent_id)
        if run is not None and run.status == SUBAGENT_PENDING:
            run.cancel_note = "队列管理面取消"
            transitionRun(run, SUBAGENT_FAILED, cause=SUBAGENT_CAUSE_CANCELLED)
            run.cause = SUBAGENT_CAUSE_CANCELLED
            run.error = "subagent_cancelled（队列管理面取消；任务未执行，可直接重派）"
            run.finished_at = time.time()
            self._logRunEvent(run, "terminal", {
                "status": run.status, "cause": run.cause,
                "terminal_quality": getattr(run, "terminal_quality", ""),
                "error": run.error, "duration_ms": round(run.duration * 1000, 3),
            })
        return entry

    def editRunTask(self, subagent_id: str, new_task: str) -> Dict[str, Any]:
        """任务书修订（B4）：排队中改写任务书（requeued）；在跑经 steer 队列注入
        （steered）；两者都不可能时诚实拒绝（rejected，带原因）。"""
        from neurova.core.steer_queue import get_steer_queue

        with self._lock:
            run = self._runs.get(subagent_id)
        memberSession = str(getattr(run, "member_session_id", "") or "") if run is not None else ""

        def _steer(sid: str, text: str) -> bool:
            return bool(memberSession) and get_steer_queue().push(memberSession, text)

        result = _runQueue().editTask(subagent_id, new_task, steer_fn=_steer)
        if result.get("mode") == "requeued" and run is not None:
            run.task = new_task  # 排队任务书改写同步回 run（状态投影一致）
        return result

    def pushParentMail(self, run: SubAgentRun, tag: str, envelope: Dict[str, Any], priority: str = "normal") -> bool:
        """父会话邮箱投递的**唯一写点**（邮箱写点单源钉子：生产面只许 swarm.py 一处写）。

        终态回灌/卡死提醒/升级/结果提交/审批信封（P3-1）都经这里投递；
        仅 chat/team_dispatch 来源且有会话才投（workflow 的报告交引擎 output；
        room_collab 的报告经候选板/房间通道，房间会话无 loop 排空邮箱）；
        失败不影响调用方主流程（诚实 debug，不吞成无声）。
        `priority` 透传邮箱优先级队列（S2）：审批/升级类投递默认 high。

        B1 投递账本：嵌套派生（有父 run）的结果投递同步落投递单——入箱即
        claimed、入箱失败即 dispose 留痕；父 run 已终态时立即触发一次补投
        （catch-up），防"子结果到时父已收工"的静默丢失。
        """
        if run.origin not in ("chat", "team_dispatch") or not run.session_id:
            return False
        messageId = f"dlv_{uuid.uuid4().hex[:16]}"
        # A3 effect outbox：投递前先落持久意图（崩溃时内存账本/邮箱皆丢，意图仍在，
        # 启动对账按 messageId 重投——邮箱幂等去重，宁重不丢）。fail-open：outbox
        # 故障不阻断投递主流程（与下方投递单落账同纪律）。
        try:
            _mailOutbox().recordIntent(messageId, run.session_id, {
                "session_id": run.session_id,
                "message_id": messageId,
                "tag": tag,
                "envelope": envelope,
                "priority": priority,
            })
        except Exception as e:  # noqa: BLE001 - outbox 意图登记失败不阻断投递主流程
            logger.debug("Swarm: outbox 意图登记失败 (%s): %s", run.subagent_id, e)
        ticket = None
        parentRunId = str(getattr(run, "parent_subagent_id", "") or "")
        if parentRunId:
            try:
                ticket = _deliveryLedger().record(
                    run.subagent_id, parentRunId, tag, envelope, messageId,
                    generation=int(run.depth or 0),
                )
            except Exception as e:  # noqa: BLE001 - 投递单落账失败不阻断投递主流程
                logger.debug("Swarm: 投递单落账失败 (%s): %s", run.subagent_id, e)
        try:
            from neurova.agent.mailbox import get_agent_mailbox

            delivered = get_agent_mailbox().push(
                run.session_id,
                f"[{tag}] " + json.dumps(envelope, ensure_ascii=False),
                priority=priority,
                message_id=messageId,
            )
        except Exception as e:  # noqa: BLE001 - 投递失败不影响主流程
            logger.debug("Swarm: 父会话邮箱投递失败 (%s): %s", run.subagent_id, e)
            delivered = False
        if delivered:
            # A3：投递成功即销账 outbox 意图；销账失败留 pending，启动对账重投
            # （重投同 messageId 被邮箱幂等去重，宁重不丢）。fail-open 同上。
            try:
                _mailOutbox().markDelivered(messageId)
            except Exception as e:  # noqa: BLE001 - outbox 销账失败不阻断投递主流程
                logger.debug("Swarm: outbox 意图销账失败 (%s): %s", messageId, e)
        if ticket is not None:
            if delivered:
                _deliveryLedger().claim(ticket["ticket_id"])
            else:
                try:
                    _deliveryLedger().dispose(ticket["ticket_id"], "mailbox_push_failed")
                except Exception as e:  # noqa: BLE001 - 处置留痕失败仅记调试
                    logger.debug("Swarm: 投递单处置失败 (%s): %s", ticket["ticket_id"], e)
        if delivered and parentRunId:
            with self._lock:
                parentRun = self._runs.get(parentRunId)
            if parentRun is not None and parentRun.status in SUBAGENT_FINISHED_STATUSES:
                self._deliveryCatchUp(parentRunId)
        return delivered

    def _deliveryCatchUp(self, parent_run_id: str) -> List[Dict[str, Any]]:
        """父 run 终结时对其名下未销账投递单补投一次（B1）。

        补投走同一会话邮箱（高优先级、独立 messageId 防邮箱幂等去重吞件），
        信封带 ``delivery_catchup`` 标记供消费方识别；无投递通道（父 run 无
        会话）则显式 dispose 留痕，不静默悬挂。
        """
        with self._lock:
            parentRun = self._runs.get(str(parent_run_id or ""))
        if parentRun is None or not parentRun.session_id:
            for stale in _deliveryLedger().pendingForParent(parent_run_id):
                try:
                    _deliveryLedger().dispose(stale["ticket_id"], "parent_run_finished_no_channel")
                except Exception as e:  # noqa: BLE001 - 处置留痕失败仅记调试
                    logger.debug("Swarm: 补投前处置失败 (%s): %s", stale["ticket_id"], e)
            return []

        def _deliver(ticket: Dict[str, Any]) -> bool:
            from neurova.agent.mailbox import get_agent_mailbox

            catchupEnvelope = dict(ticket.get("envelope") or {})
            catchupEnvelope["delivery_catchup"] = True
            return get_agent_mailbox().push(
                parentRun.session_id,
                f"[{ticket.get('tag') or '子Agent结果'}·补投] "
                + json.dumps(catchupEnvelope, ensure_ascii=False),
                priority="high",
                message_id=f"{ticket.get('message_id')}-cu",
            )

        return _deliveryLedger().catchUp(parent_run_id, _deliver)

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
        self._logRunEvent(run, "escalated", {
            "reason": run.escalation["reason"], "severity": run.escalation["severity"],
            "suggested_action": run.escalation["suggested_action"],
        })
        self.pushParentMail(run, "子Agent升级", envelope, priority="high")
        # S9：run 关联协作房间时，升级同步上墙（人在环闭环的房间呈现面）
        try:
            from neurova.agent.approval_chain import notifyRoomEscalation

            notifyRoomEscalation(run, envelope)
        except Exception as e:  # noqa: BLE001 - 房间投递失败不影响升级主流程
            logger.debug("Swarm: 升级房间投递失败 (%s): %s", run.subagent_id, e)
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
        self._logRunEvent(run, "result_submitted", {"status": run.submitted_result["status"]})
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
    "currentSubagentId",
    "current_subagent_depth",
    "get_swarm_manager",
    "reconcileSwarmRunsAtStartup",
    "resetCurrentSubagentId",
    "reset_subagent_depth",
    "reset_swarm_manager",
    "setCurrentSubagentId",
    "set_subagent_depth",
]
