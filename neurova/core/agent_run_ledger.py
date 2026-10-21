# -*- coding: utf-8 -*-
"""回合台账与让位闸的执行体——四条目共用的一份实现。

为什么从 `api/endpoints/console.py` 搬出来（§6-46，教义第 6/7 条）：让位闸护的是
**同一份模型额度**，而额度是多入口共享的（网页 `/console/chat`、公开 API `/v1/chat`
与 `/v1/chat/stream`、渠道入站 `channels/channel_router.py`）。闸与台账住在 console
一个端点文件里时，其余三条入口只有两种下场——各抄一份（四份独立漂移），或者根本不接
（限额语义从"全局"降级成"网页面自己那一份"）。本模块把两者收成一处，四个入口都改指它。

不变量沿用 `agent_run_store` 那一套（先落库再执行、同 session 单活 + FIFO、终态单点
收敛、fail-open 不阻断应答），另加两条闸口语义：

- **挂起不是失败也不是成功**：闸判"等不到额度"时行转 `parked`（非终态）并把待跑载荷
  入库；台账没接上时如实回 `ledgerFailed`，调用方**必须**报错——没落库的"已挂起"
  没有任何人能续，那就是 §6-5 那条链最擅长犯的"回一个好看的假状态"。
- **载荷带 `entry`**：续跑要回到**它原来那条入口**去重建请求。`/v1/chat` 的
  `temperature`/`max_tokens` 与控制台的 `thinking_*`/`file_ids` 语义不同，一律按
  网页请求重建会静默丢参数——丢哪个都不是"近似重跑"，是另一轮对话。
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
import typing
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, FrozenSet, List, Optional

from neurova.agent.turn_coordinator import (
    YieldGateOutcome,
    reportTurnOutcome,
    requestYieldGate,
)
from neurova.core.logger import get_logger

logger = get_logger(__name__)

ENTRY_CONSOLE = "console"
ENTRY_V1CHAT = "v1chat"
ENTRY_V1CHAT_STREAM = "v1chat_stream"
ENTRY_CHANNEL = "channel"

#: 客户端显式选型入口：这里的模型变化是用户的决定，不是 agent 漂移。
#: 渠道/自动入口不在名单里——它们未来若开始传显式模型，仍按漂移判。
CLIENT_SELECTED_ENTRIES: FrozenSet[str] = frozenset(
    {ENTRY_CONSOLE, ENTRY_V1CHAT, ENTRY_V1CHAT_STREAM}
)


def adoptsModelSwitchForEntry(entry: str) -> bool:
    """入口 → 是否采纳客户端模型改选（策略单源，四个入口共用）。"""
    return str(entry or "") in CLIENT_SELECTED_ENTRIES


#: 每次真正入睡前的通知口（续租与进度播报都属调用方，闸不认识它们）
WaitObserver = Callable[..., Awaitable[None]]


@dataclass(frozen=True)
class TurnAdmission:
    """闸的准入结论 + 挂起是否真落了库。

    `allowed=True` 时 `parkReason` 恒空；`allowed=False` 且 `ledgerFailed=True`
    意味着"判了挂起却没落库"，调用方必须走诚实失败，不能发 parked 事件糊弄过去。
    """

    allowed: bool
    parkReason: str = ""
    runId: str = ""
    attempts: int = 0
    waitedSeconds: float = 0.0
    ledgerFailed: bool = False
    outcome: Optional[YieldGateOutcome] = None

    @property
    def parked(self) -> bool:
        return not self.allowed and not self.ledgerFailed


class AgentRunLedger:
    """一次 chat run 的持久化台账（语义见 `agent_run_store` 模块注释）。

    `attach(task)` 供有后台任务的入口（网页/流式 API）挂完成回调；没有任务的入口
    （渠道、`/v1/chat` 非流式）跑完后直接调 `settleResult(result)`——两者共用同一份
    终态映射，不搞两套"看起来一样、改的时候只改一处"的收敛逻辑。
    """

    HEARTBEAT_SECONDS = 5.0

    def __init__(
        self,
        session_id: str,
        user_id: str,
        agent_id: str,
        message: str,
        run_id: Optional[str] = None,
    ):
        self.session_id = session_id
        self._args = (session_id, user_id, agent_id, message)
        # 续跑通道：给定 run_id 就**复用该行**，不再 intake——否则一个挂起过的
        # 回合会在库里长出第二个身份，"这条到底跑没跑过"就读不准了。
        self._preset_run_id = run_id
        self.run_id: Optional[str] = None
        self.rejected = False
        self._store = None
        self._owner: Optional[str] = None
        self._last_hb = 0.0

    async def acquire(self) -> List[Dict[str, Any]]:
        """登记并等待队头晋升 running；返回需先行的事件（queued / 超时 error+done）。"""
        try:
            from neurova.core import agent_run_store as _ars

            if not _ars.run_gate_enabled():
                return []
            store = _ars.get_agent_run_store()
            if self._preset_run_id is None:
                run_id = await asyncio.to_thread(store.intake, *self._args)
            else:
                run_id = self._preset_run_id
            self._owner = _ars.OWNER_IDENTITY
            wait_max = float(os.environ.get("NEUROVA_RUN_QUEUE_WAIT") or 120.0)
            deadline = time.monotonic() + wait_max
            events: List[Dict[str, Any]] = []
            last_note = 0.0
            while True:
                claimed = await asyncio.to_thread(store.claim_next, self.session_id)
                if claimed == run_id:
                    self.run_id, self._store = run_id, store
                    return events
                # P1-#8：排队等待期消费持久取消意图（/chat/stop 对 queued 行打标即
                # 在此被吸收——stopped+done 收尾，行弃列为 cancelled）
                if await asyncio.to_thread(store.cancel_requested, run_id):
                    await asyncio.to_thread(store.abandon, run_id, "user_stopped_while_queued")
                    self.run_id = None
                    events.append({"type": "stopped", "session_id": self.session_id})
                    events.append({"type": "done", "session_id": self.session_id})
                    self.rejected = True
                    return events
                now = time.monotonic()
                if now - last_note >= 1.0:
                    pos = await asyncio.to_thread(store.queued_position, run_id)
                    events.append({"type": "queued", "session_id": self.session_id, "position": pos})
                    last_note = now
                if now > deadline:
                    # 排队超时：如实报错并弃列（不让占用者的幽灵挡住后来者太久）
                    await asyncio.to_thread(store.abandon, run_id, "queue_timeout")
                    events.append(
                        {"type": "error", "message": "该会话已有运行中的任务，排队等待超时，请稍后再发"}
                    )
                    events.append({"type": "done", "session_id": self.session_id})
                    self.rejected = True
                    return events
                await asyncio.sleep(0.25)
        except Exception:  # noqa: BLE001 - fail-open：台账故障不阻断应答
            logger.warning("AgentRun 台账登记失败（fail-open，本轮不受影响）", exc_info=True)
            self.run_id = None
            return []

    async def heartbeat(self, force: bool = False) -> None:
        """续租（内部 5s 节流；主循环每轮调用，空闲时 15s ping 分支保底）。

        `force=True` 供让位等待期使用：那种等待按拍板可长到 200s，节流会让整段等待
        一次租都不续，`reconcile_stale` 便把这条 run 误杀成 failed。扫描已是现役周期
        任务（app lifespan 起，间隔 = 租约/3），所以"等待期不续租"不再是理论风险。
        """
        if self.run_id is None:
            return
        now = time.monotonic()
        if not force and now - self._last_hb < self.HEARTBEAT_SECONDS:
            return
        self._last_hb = now
        try:
            await asyncio.to_thread(self._store.heartbeat, self.run_id, self._owner)
        except Exception:  # noqa: BLE001 - 续租失败下轮再试，reconcile 兜底
            logger.debug("AgentRun 台账心跳失败（忽略）", exc_info=True)

    async def parkTurn(self, parkReason: str, payload: Dict[str, Any]) -> bool:
        """闸判"该挂起"时由执行体调用：running → parked，载荷入库供人工续跑。"""
        if self.run_id is None or self._store is None:
            return False
        try:
            return await asyncio.to_thread(
                self._store.park, self.run_id, self._owner, parkReason, payload
            )
        except Exception:  # noqa: BLE001 - 台账写挂起失败要让调用方知道（不静默转成功）
            logger.warning("AgentRun 台账挂起写入失败", exc_info=True)
            return False

    def attach(self, task: "asyncio.Task") -> None:
        if self.run_id is not None:
            task.add_done_callback(self.settle)

    def settle(self, task: "asyncio.Task") -> None:
        """task 完成回调 = 终态单点收敛（独立线程写库，回调上下文无 running loop 依赖）。"""
        if task.cancelled():
            self._finishAs("cancelled", "stopped")
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:  # pragma: no cover - 回调期任务已被取消
            self._finishAs("cancelled", "stopped")
            return
        if exc is not None:
            self._finishAs("failed", "chat_error")
            return
        self.settleResult(task.result() if isinstance(task.result(), dict) else {})

    def settleResult(self, result: Dict[str, Any]) -> None:
        """无后台任务的入口（渠道、非流式 API）跑完直接按结果落终态。"""
        if result.get("parked"):
            # 行已由 parkTurn 转成 parked（非终态，等人续跑）；这里再写终态
            # 就等于把"等人"抹成"已结束"
            return
        if result.get("stopped"):
            self._finishAs("cancelled", "user_stopped")
        elif result.get("error"):
            self._finishAs("failed", "chat_error")
        else:
            self._finishAs("completed", None)

    def _finishAs(self, status: str, errorType: Optional[str]) -> None:
        if self.run_id is None or self._store is None:
            return
        store, run_id, owner = self._store, self.run_id, self._owner

        def _fin():
            try:
                if not store.finish(run_id, owner, status, errorType):
                    logger.debug("AgentRun 终态被 owner 栅栏拒绝（已被对账收敛）: run=%s", run_id)
            except Exception:  # noqa: BLE001 - 台账收尾失败仅日志
                logger.warning("AgentRun 台账终态写入失败（忽略）", exc_info=True)

        threading.Thread(target=_fin, daemon=True).start()


async def requestTurnAdmission(
    *,
    ledger: AgentRunLedger,
    agentId: str,
    modelName: str,
    sessionId: str,
    userInput: str,
    payload: Dict[str, Any],
    onWait: Optional[WaitObserver] = None,
) -> TurnAdmission:
    """问一次闸；判挂起就把这一行转 `parked` 并存好续跑载荷。

    四个入口都走这里——**闸口只此一处调用**（判据
    `test_v1ChatRunLedger.TestLedgerImplementationIsSingleSource` 钉住），否则下一轮
    改 park 语义时只会改到一处，其余入口静默留着旧形态。

    模型改选的策略也从这里派生：`payload.entry` 是客户端显式选型入口时，换模型
    是用户的决定，闸应重设 pin 并放行（见 `adoptsModelSwitchForEntry`）。
    """
    entry = str(payload.get("entry") or "")
    outcome: YieldGateOutcome = await requestYieldGate(
        agentId=agentId,
        modelName=modelName or "",
        sessionId=sessionId,
        userInput=userInput,
        adoptModelSwitch=adoptsModelSwitchForEntry(entry),
        onWait=onWait,
    )
    if outcome.proceeded:
        return TurnAdmission(
            allowed=True,
            runId=ledger.run_id or "",
            attempts=outcome.attempts,
            waitedSeconds=outcome.waitedSeconds,
            outcome=outcome,
        )

    # 挂起原因里的冲突双方（pinned/requested）随载荷落库：SSE 是一次性的，
    # 刷新后 `GET /chat/runs` 只能从库里把"为什么挂"读回来。只并入一份新 dict，
    # 不改调用方传进来的载荷。
    parkPayload = dict(payload)
    parkPayload["park_details"] = dict(outcome.details or {})
    parked = await ledger.parkTurn(outcome.parkReason, parkPayload)
    return TurnAdmission(
        allowed=False,
        parkReason=outcome.parkReason,
        runId=ledger.run_id or "",
        attempts=outcome.attempts,
        waitedSeconds=outcome.waitedSeconds,
        ledgerFailed=not parked,
        outcome=outcome,
    )


async def reportAdmissionOutcome(admission: Optional[TurnAdmission], success: bool) -> None:
    """回合跑完后回填 pacing 统计（Layer 3 间距/自适应节律的判据来源）。

    只有**放行过**的回合才回填：没跑的操作记成完成，节律统计就说假话。
    这里刻意不自起后台任务——仓里已登记过"句柄丢弃 → 关停无法收敛"的病灶（§6-21/R8），
    要异步由调用方决定并持有句柄。
    """
    if admission is None or admission.outcome is None:
        return
    await reportTurnOutcome(outcome=admission.outcome, success=success)


def parkReceiptText(admission: TurnAdmission, *, resumableWhere: str) -> str:
    """挂起回执的统一措辞（渠道等非流式面用）。

    必须带 run_id：那是唯一续跑凭据。也必须说清**在哪**续跑——渠道挂起的这一轮
    在属主的网页会话里续，回复写进会话，渠道侧不再收到推送；含糊成"请稍后再试"
    等于让用户以为会自动重来。
    """
    waited = f"，已等 {admission.waitedSeconds:.0f}s" if admission.waitedSeconds else ""
    return (
        f"本轮已挂起（原因 {admission.parkReason or 'unspecified'}，判定 {admission.attempts} 次{waited}），"
        f"额度恢复不会自动重来。凭据 run_id={admission.runId}，{resumableWhere}。"
    )


def resumeTurnIdentity(
    row: Dict[str, Any], currentUserId: str, currentAgentId: str = ""
) -> typing.Tuple[str, str]:
    """续跑时的执行身份＝**原回合属主**，不是点按钮的那个人。

    管理员有"点续跑"的权限，没有把这一轮改成"以管理员身份执行"的权力：记忆、画像、
    用量都跟着 user_id 走，跟着点击者走就是接线顺手造出来的越权面。四个入口共用这一份
    推导，避免"网页那条改了、API 那条还照着请求者跑"。
    """
    return (
        str(row.get("user_id") or "") or currentUserId,
        str(row.get("agent_id") or "") or currentAgentId,
    )


# ── 蜂群子任务的台账记账（§6-78 L 条 / §6-85）──────────────────────
#: 子任务收尾的**成因**词值。写侧（`swarm._execute`）与这里共用同一份常量——
#: 台账的 `error_type` 由它翻译而来，不再靠嗅探错误字符串。
SUBAGENT_CAUSE_NONE = ""
SUBAGENT_CAUSE_TIMEOUT = "subagent_timeout"
SUBAGENT_CAUSE_CANCELLED = "subagent_cancelled"
SUBAGENT_CAUSE_FAILED = "subagent_failed"

#: 蜂群状态 → 台账终态。completed 直落；取消归 `cancelled`（台账本就有这个词，
#: 且 `reconcile_at_startup`/统计都认它）；其余失败归 `failed` 并留成因。
_SUBAGENT_TERMINAL_MAP = {
    "completed": ("completed", ""),
    SUBAGENT_CAUSE_CANCELLED: ("cancelled", SUBAGENT_CAUSE_CANCELLED),
    SUBAGENT_CAUSE_TIMEOUT: ("failed", SUBAGENT_CAUSE_TIMEOUT),
}


def subagentTerminalRow(runStatus: str, cause: str) -> typing.Tuple[str, str]:
    """把蜂群的一条收尾翻成台账的 (status, error_type)。唯一一处翻译。"""
    if cause in _SUBAGENT_TERMINAL_MAP:
        return _SUBAGENT_TERMINAL_MAP[cause]
    if runStatus == "completed":
        return ("completed", "")
    return ("failed", cause or SUBAGENT_CAUSE_FAILED)


def openSubagentRun(
    *, memberSessionId: str, subagentId: str, parentSessionId: str,
    userId: str, agentId: str, task: str,
) -> Optional[str]:
    """子任务进台账：`intake` → 晋升 `running`。返回 run_id，失败返回 None。

    **同步而非协程**：终态必须写回，而取消路径上协程 `await` 会被第二次 cancel 打断
    （行就永久停在 running——正是 §6-84 刚收掉的那类半死态）。台账这几步是短 SQL，
    起止各一次，不在高频流式循环里。

    **为什么不走 `AgentRunLedger.acquire()`**：那条是回合准入闸（排队、让位、park
    等人工续跑），而 park 对子任务没有对应 UI——把它塞进让位闸会造出"挂着等人点的
    子任务"这种新产品形态，那是另一件事。这里只用同一张表、同一套终态枚举与 owner
    栅栏（写侧仍只在本模块，不另建第二处 INSERT），把「这单子任务跑过、跑到哪一步」
    记下来。是否让子任务参与让位闸属需人裁，已登记台账。
    """
    try:
        from neurova.core import agent_run_store as _ars

        if not _ars.run_gate_enabled():
            return None
        store = _ars.get_agent_run_store()
        run_id = store.intake(memberSessionId, userId, agentId, task,
                              subagentId, parentSessionId)
        claimed = store.claim_next(memberSessionId)
        if claimed != run_id:
            # 没晋升（同 member 会话已有 running 行）→ 弃 queued 行，绝不留幽灵 running
            store.abandon(run_id, "subagent_not_promoted")
            return None
        return run_id
    except Exception as e:  # noqa: BLE001 - 台账故障永不阻断子任务（与回合面同口径）
        logger.warning("子任务台账登记失败（不阻断执行）: %s", e)
        return None


def closeSubagentRun(run_id: Optional[str], runStatus: str, cause: str = "") -> None:
    """写终态。owner 栅栏沿用台账本体；`run_id` 为 None（登记失败/gate off）即静默跳过。"""
    if not run_id:
        return
    try:
        from neurova.core import agent_run_store as _ars

        store = _ars.get_agent_run_store()
        status, errorType = subagentTerminalRow(runStatus, cause)
        store.finish(run_id, _ars.OWNER_IDENTITY, status, errorType)
    except Exception as e:  # noqa: BLE001 - 终态写不回时由启动收敛兜，不在这里炸子任务
        logger.warning("子任务台账终态写入失败(%s): %s", run_id, e)
