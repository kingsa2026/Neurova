"""
swarm_support — 蜂群 run 生命周期支撑（自 neurova/agent/swarm.py 纯移动拆出）

承载「子任务 run」的词汇、记录与状态机面，供 SwarmManager（swarm.py 编排核心）
与外部消费方（review_gate、api.app 启动接线、测试）共用：

- SUBAGENT_* 状态词汇（§6-78 K 条唯一出处）与 RUN_STATUS_TRANSITIONS 迁移表；
- SubAgentRun：一次子 Agent 运行的状态记录；
- transitionRun：run 状态迁移唯一收口（S3）；
- buildRunLineage：F5 谱系投影单源；
- replayRunTailStatus / reconcileSwarmRunsAtStartup：启动收敛（事件账本侧补强）。

拆分是纯移动：逻辑、签名、异常语义与原文件逐字一致。两处对单例入口
`get_swarm_manager` 的引用改为函数内惰性 import（仍是调用期解析，语义不变——
monkeypatch `neurova.agent.swarm.get_swarm_manager` 依旧生效，且不产生模块级
循环依赖；swarm.py 侧经再导出保持原有名字与打桩点）。
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 纯移动保真：沿用原模块的 logger 名，日志观测面（logger 名/路由）不变。
logger = logging.getLogger("neurova.agent.swarm")

# ── 子任务状态词汇的唯一出处（§6-78 K 条）──────────────────────────
# 改前这六个词值散在 swarm.py 六处（dataclass 默认、返回投影、list_active、
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

# ── A1：终态质量分级词值（本模块唯一出处）──────────────────────────
#: classifyTerminalQuality 的三档输出——验收门/评审门据此决定是否需要复核。
TERMINAL_QUALITY_STRONG = "strong"
TERMINAL_QUALITY_WEAK = "weak"
TERMINAL_QUALITY_NONE = "none"

# ── S3：run 生命周期迁移表（唯一收口 transitionRun）────────────────────
# 迁移合法性从各赋值点收拢到这一张表：键=现役状态，值=允许去的下一态集合。
# 终态（completed/failed）无出边；pending 只能启动或直接判失败（依赖门拦下/
# 等待中被叫停，均未执行）；in_review 可回 running（放行/回炉/降级）、可直接
# 完成、也可判失败（评审期被叫停）。改状态赋值点一律走 transitionRun。
RUN_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    SUBAGENT_PENDING: frozenset({SUBAGENT_RUNNING, SUBAGENT_FAILED}),
    SUBAGENT_RUNNING: frozenset({SUBAGENT_IN_REVIEW, SUBAGENT_COMPLETED, SUBAGENT_FAILED}),
    SUBAGENT_IN_REVIEW: frozenset({SUBAGENT_RUNNING, SUBAGENT_COMPLETED, SUBAGENT_FAILED}),
    SUBAGENT_COMPLETED: frozenset(),
    SUBAGENT_FAILED: frozenset(),
}


class IllegalRunStatusTransition(RuntimeError):
    """非法 run 状态迁移（迁移表拒绝）——显式暴露，不静默、不吞、不改状态。"""


def buildRunLineage(run: "SubAgentRun", runsMap: Optional[Dict[str, "SubAgentRun"]] = None,
                    walkLimit: int = 16) -> Dict[str, Any]:
    """F5 谱系投影单源：run → 事件 lineage（设计文档 §3.5）。

    - agent_path 沿 ``parent_subagent_id`` 上溯（``runsMap`` 内存 run 表优先）、
      根→叶顺序；父 run 已被逐出/跨进程时其 id 仍入路径（谱系不断链）；
      限深 ``walkLimit``（16 层远超派生深度治理上限）、访问集防环。
    - 模块级：``SwarmManager._runLineage`` 与模块级 ``transitionRun``（无 self）
      共用这一份——status_changed 与其余 run 事件同谱系，不留第二套拼装。
    """
    chain: List[str] = []  # 叶→根
    visited: set = set()
    cursor: Optional[SubAgentRun] = run
    while cursor is not None and len(chain) < walkLimit:
        sid = str(getattr(cursor, "subagent_id", "") or "")
        if not sid or sid in visited:
            break
        visited.add(sid)
        chain.append(sid)
        parentId = str(getattr(cursor, "parent_subagent_id", "") or "")
        if not parentId or parentId in visited:
            break
        parent = (runsMap or {}).get(parentId)
        if parent is None:
            # 父 run 不在内存（已逐出/跨进程）：id 仍入路径后停止上溯
            chain.append(parentId)
            visited.add(parentId)
            break
        cursor = parent
    chain.reverse()  # 根→叶
    return {
        "tenant_id": getattr(run, "tenant_id", ""),
        "team_id": getattr(run, "team_id", ""),
        "project_id": getattr(run, "project_id", ""),
        "room_id": getattr(run, "room_id", ""),
        "depth": getattr(run, "depth", 0),
        "parent_subagent_id": getattr(run, "parent_subagent_id", ""),
        "agent_path": chain,
        "trace_id": getattr(run, "trace_id", ""),
        "parent_trace_id": getattr(run, "parent_trace_id", ""),
    }


#: 视作「provider 明确完成」的正常完成成因（A1）：空（无成因直完）与
#: candidate_merged（S4 候选合入——swarm 主链路唯一的 completed 迁移仪式）。
#: 其余完成成因（超时/取消兜底、可疑成因）一律按 weak 处理。
STRONG_COMPLETION_CAUSES = frozenset({"", "candidate_merged"})


def classifyTerminalQuality(status: str, cause: str) -> str:
    """终态可信度分级（A1）：验收门/评审门据此决定是否需要复核确认。

    映射表（cause 词值见 ``agent_run_ledger.SUBAGENT_CAUSE_*``）：
    - completed + 正常完成成因（"" 或 candidate_merged，见 STRONG_COMPLETION_CAUSES）→ strong
    - completed + subagent_timeout / subagent_cancelled（兜底推断）           → weak
    - completed + 其他非空成因（完成得可疑）                                  → weak
    - failed    + 任意非空成因（timeout/cancelled/failed/crash）             → weak
    - failed    + ""（无成因，来路不明）                                      → none
    - 非终态（pending/running/in_review/未知）+ 任意                          → none
    """
    target = str(status or "").strip()
    if target not in SUBAGENT_FINISHED_STATUSES:
        return TERMINAL_QUALITY_NONE
    causeText = str(cause or "").strip()
    if target == SUBAGENT_COMPLETED:
        if causeText in STRONG_COMPLETION_CAUSES:
            return TERMINAL_QUALITY_STRONG
        return TERMINAL_QUALITY_WEAK  # 超时/取消兜底或可疑成因：完成不可信，按弱可信处理
    # failed：有成因可追 → weak；无成因 → none（来路不明，必须复核）
    if causeText:
        return TERMINAL_QUALITY_WEAK
    return TERMINAL_QUALITY_NONE


def requiresReviewConfirmation(run: "SubAgentRun") -> bool:
    """该 run 的终态是否需要复核确认（A1）：weak/none → True，strong → False。

    供验收门/评审门决定是否加一道复核；空串（尚未到终态）返回 False——
    复核针对的是已有终态结果的可信度，非终态本就无结果可确认。
    """
    quality = str(getattr(run, "terminal_quality", "") or "")
    return quality in (TERMINAL_QUALITY_WEAK, TERMINAL_QUALITY_NONE)


def transitionRun(run: "SubAgentRun", newStatus: str, cause: str = "") -> str:
    """run 状态迁移唯一收口（S3）：迁移表强校验 + status_changed 事件归档。

    - 合法迁移：改状态并落一条 status_changed 事件（复用 H-4 账本，因果链沿
      last_event_id 串接；归档故障 fail-open，不阻断状态机——与 H-4 同纪律）；
    - 非法迁移：显式抛 IllegalRunStatusTransition，状态保持不变；
    - 同态重申：幂等 no-op（不抛错、不重复落事件）。
    返回迁移后的状态。
    """
    from neurova.agent.swarm import get_swarm_manager

    target = str(newStatus or "").strip()
    if target not in SUBAGENT_STATUSES:
        raise IllegalRunStatusTransition(
            f"未知 run 状态 {newStatus!r}（合法域 {sorted(SUBAGENT_STATUSES)}）")
    current = run.status
    if target == current:
        return current
    if target not in RUN_STATUS_TRANSITIONS.get(current, frozenset()):
        raise IllegalRunStatusTransition(
            f"非法 run 状态迁移 {current} → {target}"
            f"（subagent={run.subagent_id} cause={cause or 'n/a'}；"
            f"合法去向 {sorted(RUN_STATUS_TRANSITIONS.get(current, frozenset()))}）")
    run.status = target
    # A1：终态迁移同步写质量分级；同态重申（上方提前返回）与非终态迁移不动该字段。
    if target in SUBAGENT_FINISHED_STATUSES:
        run.terminal_quality = classifyTerminalQuality(target, cause)
    try:
        from neurova.agent.swarm_event_log import appendRunEvent

        # F5：status_changed 与其余 run 事件同谱系。本函数模块级无 self，
        # 借当前管理器的内存 run 表上溯 agent_path（无管理器时退化为自头路径）。
        try:
            runsMap = dict(get_swarm_manager()._runs)
        except Exception:  # noqa: BLE001 - 谱系取数失败不阻断状态机（fail-open 同纪律）
            runsMap = {}
        eventId = appendRunEvent(
            run.subagent_id, "status_changed",
            {"from": current, "to": target, "cause": str(cause or "")},
            causationId=getattr(run, "last_event_id", ""),
            lineage=buildRunLineage(run, runsMap),
        )
        run.last_event_id = eventId
    except Exception as e:  # noqa: BLE001 - 归档故障不阻断状态机（H-4 fail-open 同纪律）
        logger.debug("Swarm: status_changed 归档失败 (%s): %s", run.subagent_id, e)
    return target


def replayRunTailStatus(subagentId: str) -> str:
    """从 H-4 事件账本重放某 run 的末态（S3 启动收敛增强：补强台账，不替代）。

    取账本里最后一条 status_changed 的目标态或 terminal 的状态；账本缺失/无
    状态事件返回空串（如实说不知道，不猜）。进程重启后内存 run 表为空，台账
    （agent_run_ledger）仍是权威事实源；本函数供一致性校正与排查下钻。
    """
    from neurova.agent.swarm_event_log import readRunEvents

    tail = ""
    for event in readRunEvents(str(subagentId or "").strip()):
        if event.get("type") == "status_changed":
            tail = str((event.get("payload") or {}).get("to") or "") or tail
        elif event.get("type") == "terminal":
            tail = str((event.get("payload") or {}).get("status") or "") or tail
    return tail


def reconcileSwarmRunsAtStartup() -> Dict[str, Any]:
    """启动收敛（S3 事件账本侧接线，K2）：对「台账仍 running 的 swarm run」与
    「内存仍活跃的 run」用事件账本末态校正内存 run 状态，末态如实落台账
    （口径与 ``agent_run_store.reconcile_at_startup`` 一致：running→failed
    (process_died)——台账终态由该收敛主收口，本入口不重写台账）。

    只做状态收敛，**不做 run 复活续跑**：内存无此 run 时如实报告
    （not_in_memory），不凭账本重建对象。账本侧「cancelled」末态在蜂群域落
    failed（迁移表无 cancelled，取消成因记 cause，与 cancelRun 同口径）。
    fail-open：台账/单条 run 校正故障不阻断启动。
    """
    from neurova.agent.swarm import get_swarm_manager

    swarm = get_swarm_manager()
    candidates: List[str] = []

    # ① 台账侧候选：启动瞬间仍 running、已由台账启动收敛翻牌留档的子任务行
    try:
        from neurova.core import agent_run_store as _ars

        if _ars.run_gate_enabled():
            for row in _ars.get_agent_run_store().startupReconcileRowsSnapshot():
                sid = str((row or {}).get("subagent_id") or "").strip()
                if sid:
                    candidates.append(sid)
    except Exception as e:  # noqa: BLE001 - 台账不可用不阻断启动收敛
        logger.warning("Swarm 启动收敛：台账候选读取失败（忽略）: %s", e)

    # ② 内存侧候选：仍活跃的 run（同进程残留/漂移，例如单例跨 lifespan）
    with swarm._lock:
        for run in swarm._runs.values():
            if run.status in SUBAGENT_ACTIVE_STATUSES:
                candidates.append(run.subagent_id)

    results: List[Dict[str, Any]] = []
    for sid in dict.fromkeys(candidates):  # 去重保序
        try:
            tail = replayRunTailStatus(sid)
            if tail == "cancelled":
                tail = SUBAGENT_FAILED
            results.append(swarm.reconcileRunFromEvents(sid, tailOverride=tail))
        except Exception as e:  # noqa: BLE001 - 单 run 校正失败不拖垮整体
            logger.warning("Swarm 启动收敛：run %s 校正失败（忽略）: %s", sid, e)
            results.append({"subagent_id": sid, "corrected": False,
                            "reason": f"error: {e}"})

    corrected = [r for r in results if r.get("corrected")]
    if corrected:
        logger.warning(
            "Swarm 启动收敛：按事件账本末态校正 %d 条内存 run 状态（只收敛，不复活续跑）",
            len(corrected),
        )

    # A3 effect outbox 启动对账：进程崩溃时内存投递账本（delegated_delivery）丢失，
    # outbox 里的持久投递意图仍在——逐条重投会话邮箱（mailbox 按 messageId 幂等
    # 去重，宁重不丢、不重复生效），成功即销账。投递函数落 swarm.py（邮箱写点
    # 全仓唯一）。fail-open：outbox 故障不阻断启动收敛。
    outboxReport: Dict[str, Any] = {}
    try:
        from neurova.agent.mail_outbox import getMailOutbox
        from neurova.agent.swarm import redeliverOutboxIntent

        outboxReport = getMailOutbox().reconcile(redeliverOutboxIntent)
        if outboxReport.get("attempted"):
            logger.warning(
                "Swarm 启动收敛：outbox 补投投递意图 delivered=%s attempted=%s failed=%s",
                outboxReport.get("delivered"), outboxReport.get("attempted"),
                outboxReport.get("failed"),
            )
    except Exception as e:  # noqa: BLE001 - outbox 对账故障不阻断启动收敛
        logger.warning("Swarm 启动收敛：outbox 对账失败（忽略）: %s", e)

    return {
        "checked": len(results),
        "corrected": len(corrected),
        "results": results,
        "outbox": outboxReport,
    }


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
    # F5 谱系：发起者租户——spawn 时刻经 _currentTenantId() 读一次；台账行
    # （openSubagentRun 的 tenantId）与事件 lineage 同源，运行中不重读。
    tenant_id: str = ""
    # F5 谱系：父 run id——member 内递归派生时指向父 run（顶层派生为空串）。
    # agent_path 不落存储字段，事件写入时沿它上溯现算（见 _runLineage）。
    parent_subagent_id: str = ""
    # P3-4（评测报告 G-13）：数据面围栏扫描摘要（task_hits/payload_hits/hit_count）。
    # None = 未命中（干净任务不留标记噪音）；命中只标记与告警，不改写不阻断。
    data_fence: Optional[Dict[str, Any]] = None
    # H-4：本 run 最后一笔归档事件的 id（事件账本因果链的串接锚点；内部记账）。
    last_event_id: str = ""
    # H 批补差：父侧叫停时的原因留痕（CancelledError 落账时并入 error 文案）。
    cancel_note: str = ""
    status: str = SUBAGENT_PENDING  # 取值域见 SUBAGENT_STATUSES（本模块常量，唯一出处）
    # P2-10 增强：子代理升级/结构化结果提交（escalate/submit_result 工具写入，
    # 随邮箱投递发起者会话；只作读数与通知，不改变运行状态机）
    escalation: Optional[Dict[str, Any]] = None
    submitted_result: Optional[Dict[str, Any]] = None
    # 收尾成因（见 `agent_run_ledger.SUBAGENT_CAUSE_*`）：台账的 error_type 由它翻出来，
    # 不靠嗅探 error 文本——那正是「同一件事两份口径」的下一种形态。
    cause: str = ""
    # A1：终态质量分级（strong/weak/none，见 classifyTerminalQuality）——
    # 终态迁移时由 transitionRun 写入；非终态/同态重申保持不变。空串 = 未到终态。
    terminal_quality: str = ""
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
    # S9 团队/房间接入：room_id = 协作房间（=协作 project_id）——审批/升级/候选事件
    # 投递到该房间（人在环闭环），member 记忆按 room:<room_id> 作用域共享（共享黑板）。
    # 空串 = 不关联房间（行为与改前完全一致）。
    room_id: str = ""
    # S12：run→project 归属标（台账行 project_id 列的来源）。房间发起的协作按
    # ``room_id = 协作 project_id`` 等式取 room_id；主 agent 直发带项目上下文时
    # 显式传入。空串 = 不归属项目（档案读面不收录）。
    project_id: str = ""
    # S9 动态组队：按团队名册选中的成员与角色（角色复用 collaboration_template.AgentRole）。
    team_id: str = ""
    team_role: str = ""
    team_member: Optional[Dict[str, Any]] = None  # {user_id, name, role, prompt}
    # S10/S11：单条 run 的运行窗口覆盖（秒；0 = 用治理面默认读数）。房间协作发起人
    # 显式给预算时落在这里——只影响本 run，不改进程级 env（避免并发互踩）。
    runtime_budget_sec: float = 0.0
    # D-B（provider 中途切换放开·按租户隔离）：派生时刻的执行体档案快照，
    # 仅外部成员 run 落值（spawn 时刻单源冻结，运行中不重读）。
    # - executor_caps_snapshot：spawn 时刻 capabilitiesFor(executor.tool) 的能力档
    #   拷贝（dict）或 None；None = 本仓 agent / 存量 run（续跑按同 executor 同
    #   模型处理，向后兼容）；
    # - executor_tool：执行体目录标识（如 "opencode"），续跑时与名册现值比对得
    #   出 same_executor；
    # - executor_model：spawn 时刻解析的模型名（取不到为空串；run.model 的快照
    #   别名，续跑比较专用契约键，落值后不改写）。
    # resumeFinishedRun 据此走 decideProviderTransition 五结果决策。
    executor_caps_snapshot: Optional[Dict[str, Any]] = None
    executor_tool: str = ""
    executor_model: str = ""

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
            "terminal_quality": self.terminal_quality,
            "report": self.report,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": self.duration,
            "node_id": self.node_id,
            "execution_id": self.execution_id,
            "resumed_from": self.resumed_from,
            "room_id": self.room_id,
            "project_id": self.project_id,
            "team_id": self.team_id,
            "team_role": self.team_role,
            # D-B：执行体档案快照（新增可选键——存量消费方按缺省 None/"" 兼容）
            "executor_caps_snapshot": self.executor_caps_snapshot,
            "executor_tool": self.executor_tool,
            "executor_model": self.executor_model,
        }
