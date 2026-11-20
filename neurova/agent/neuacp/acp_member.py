# -*- coding: utf-8 -*-
"""NeuacpMemberAdapter：把外部编码代理包成 swarm 成员。

鸭子面（设计文档 §4.2，与 swarm._run_member 的调用约定严格对齐）：
- ``async chat(user_input, *, stream, session_id, metadata) -> {"text": str}``
  恒以 stream=True 被调用；必须消费 ``metadata["event_emitter"]`` 流式产出；
  失败抛异常或返回 "[LLM Error] ..." 前缀文本。
- ``config.name`` → 事件/台账/审批卡里的 agent_name。
- ``current_session_id`` = run.member_session_id。
- ``llm_client.chat`` → 验收/评审判定通道（D2 裁定提供；由装配方注入
  本仓 provider 通道）。
- ``bindRun(run, logEvent, recorder=None, spanId=None)``：swarm._run_member
  在调用 chat 前注入运行上下文（B1 审批桥接 + B2 工具镜像的锚点）。
- ``permission_asker(action, reason, context) -> dict``：同步裁决钩子。
  默认实现接审批链单源 ``requestRunApproval``（B1）；显式注入的 asker 优先。
"""
import asyncio
import logging
from types import SimpleNamespace
from typing import Any, Callable, Optional

from neurova.agent.neuacp.executor import NeuacpSessionContext
from neurova.agent.neuacp.redaction import redactFrame

logger = logging.getLogger(__name__)

#: ACP 工具调用类别 → 审批声明档（§4.4 分级建议）：读/搜索/抓取/思考类低危 L0；
#: 写/编辑/删除/执行/未知一律 L1（危险命令升档由链内 classifyActionLevel
#: 统一处理——分级只此一套，不另造第二份正则）。
ACP_LEVEL_BY_KIND = {
    "read": "L0",
    "search": "L0",
    "fetch": "L0",
    "think": "L0",
}


def acpActionLevel(action: str) -> str:
    """``acp:{tool}:{kind}`` → 审批声明档。

    非本命名空间或缺 kind 的动作保守按 L1（需人/父裁决），不静默放行。
    """
    parts = str(action or "").split(":", 2)
    if len(parts) < 3 or parts[0] != "acp":
        return "L1"
    return "L0" if parts[2].strip().lower() in ACP_LEVEL_BY_KIND else "L1"


class NeuacpMemberAdapter:
    """chat 兼容适配器：swarm 名册 executor 成员经此驱动外部执行体。"""

    def __init__(
        self,
        executor,
        *,
        name: str,
        cwd: str = "",
        permission_asker: Optional[Callable] = None,
        verify_channel: Optional[Any] = None,
        prompt_timeout: Optional[float] = None,
    ) -> None:
        self._executor = executor
        self._cwd = cwd or ""
        self._prompt_timeout = prompt_timeout
        self.config = SimpleNamespace(name=name)
        self.llm_client = verify_channel
        self.current_session_id: Optional[str] = None
        # B1/B2 运行绑定：chat 前由 swarm._run_member 经 bindRun 注入。
        self._run: Optional[Any] = None
        self._logEvent: Optional[Callable] = None
        self._recorder: Optional[Any] = None
        self._spanId: Optional[str] = None
        # B1：chat 时刻捕获的事件循环——泵线程的同步裁决经它桥回异步审批链。
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # 显式注入的 asker 优先（测试/定制面）；默认接审批链（B1）。
        self._permission_asker = permission_asker or self._approvalPermissionAsker
        self._attachToolCallMirror()

    # ── B1：运行绑定与审批桥接 ───────────────────────────────────────────

    def bindRun(self, run: Any, logEvent: Callable, recorder: Optional[Any] = None,
                spanId: Optional[str] = None) -> None:
        """绑定 swarm 运行上下文（``swarm._run_member`` 在 chat 前调用）。

        - ``run``：SubAgentRun——审批单与台账的主体；
        - ``logEvent(run, eventType, payload)``：H-4 事件账本写入口
          （swarm._logRunEvent）；
        - ``recorder``/``spanId``：member span 轨迹（TrajectoryRecorder），
          可空——无 recorder 时工具镜像只走 logEvent。
        """
        self._run = run
        self._logEvent = logEvent
        self._recorder = recorder
        self._spanId = spanId

    def _logPermissionDecision(self, run: Any, action: str, decision: dict) -> None:
        """permission 裁决落 H-4 账本（F2 断点 8 补账，设计文档 §3.2）。

        payload 五键：action/approved/pending/denied/reason；先过 redactFrame
        （reason 可能夹带凭据形态，F3 脱敏前置）；fail-open——落账故障只记
        debug，绝不阻断裁决应答回传泵线程。
        """
        logEvent = self._logEvent
        if not callable(logEvent):
            return
        try:
            payload = redactFrame({
                "action": action,
                "approved": bool(decision.get("approved")),
                "pending": bool(decision.get("pending")),
                "denied": bool(decision.get("denied")),
                "reason": str(decision.get("reason") or ""),
            })
            logEvent(run, "permission_decided", payload)
        except Exception as exc:  # noqa: BLE001 - 账本故障不阻断审批应答
            logger.debug("permission_decided 落账失败: %s", exc)

    def _approvalPermissionAsker(self, action: str, reason: str, context: str) -> dict:
        """session/request_permission → ``requestRunApproval``（审批链单源）。

        调用发生在 ACP 泵线程（NeuacpClient 的 request handler），必须同步
        返回：审批协程经 ``asyncio.run_coroutine_threadsafe`` 投回 chat 时刻
        捕获的事件循环，``result(timeout)`` 桥接为同步应答。超时预算取
        ``NEUROVA_SWARM_APPROVAL_WAIT_S``（审批链同源读数），另加 5s 桥接
        宽限——让链内审批超时先到，回传诚实的 pending/denied 形态而非桥接
        超时异常。未 bindRun / 无循环 / 桥接失败一律 deny（fail-closed）。

        F2：拿到裁决后（含桥接失败路径，run 存在即记）落 permission_decided
        事件；run 未绑定的路径无从归属，维持不落账。
        """
        run = self._run
        loop = self._loop
        if run is None or loop is None:
            decision = {
                "approved": False, "pending": False, "denied": True,
                "reason": "external_member_not_bound",
            }
            if run is not None:
                # run 已绑定但事件循环缺失（罕见）：裁决照记，便于审计追溯
                self._logPermissionDecision(run, action, decision)
            return decision
        from neurova.agent.approval_chain import approvalWaitSeconds, requestRunApproval

        coro = requestRunApproval(
            run,
            action,
            reason=reason,
            level=acpActionLevel(action),
            context=context or "acp_permission",
        )
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            decision = future.result(timeout=approvalWaitSeconds() + 5.0)
        except Exception as exc:  # noqa: BLE001 - 桥接故障按拒绝收口（fail-closed）
            logger.warning("外部成员审批桥接失败，按 deny 处理 (action=%s): %s", action, exc)
            decision = {
                "approved": False, "pending": False, "denied": True,
                "reason": f"approval_bridge_failed: {exc}",
            }
        self._logPermissionDecision(run, action, decision)
        return decision

    # ── B2：工具调用镜像 ─────────────────────────────────────────────────

    def _attachToolCallMirror(self) -> None:
        """把镜像回调挂到执行体：优先 setToolCallHandler（StdioExecutor），
        退回 ``_on_tool_call`` 属性（无该方法的自定义/插件执行体）。"""
        register = getattr(self._executor, "setToolCallHandler", None)
        if callable(register):
            try:
                register(self._mirrorToolCall)
                return
            except Exception as exc:  # noqa: BLE001 - 挂钩失败退回属性注入
                logger.debug("setToolCallHandler 挂载失败，退回属性注入: %s", exc)
        if hasattr(self._executor, "_on_tool_call"):
            try:
                self._executor._on_tool_call = self._mirrorToolCall
            except Exception as exc:  # noqa: BLE001 - 镜像是可观测面，失败不阻断
                logger.debug("工具镜像挂载失败（不阻断外部执行）: %s", exc)

    def _mirrorToolCall(self, update: dict) -> None:
        """tool_call(_update) → H-4 账本 + member span 轨迹（§4.4/§6.3：
        外部代理工具不纳管执行、但全量可见）。可在泵线程被调，fail-open。

        F3（设计文档 §3.3）：update 先过 redactFrame 再进账本/轨迹——工具
        参数可能夹带密钥；redactFrame 深拷贝脱敏，原 update 不被就地改写。
        """
        run = self._run
        if run is None:
            return
        redacted = redactFrame(update if isinstance(update, dict) else {})
        logEvent = self._logEvent
        if callable(logEvent):
            try:
                logEvent(run, "tool_call", redacted)
            except Exception as exc:  # noqa: BLE001 - 账本故障不阻断外部执行
                logger.debug("tool_call 账本镜像失败: %s", exc)
        recorder = self._recorder
        if recorder is not None and getattr(run, "trace_id", ""):
            try:
                recorder.record_event(
                    run.trace_id,
                    "info",
                    {
                        "event": "tool_call",
                        "subagent_id": run.subagent_id,
                        "agent_name": run.agent_name,
                        "tool_call": redacted,
                    },
                    span_id=self._spanId,
                )
            except Exception as exc:  # noqa: BLE001 - 轨迹故障不阻断外部执行
                logger.debug("tool_call 轨迹镜像失败: %s", exc)

    # ── swarm 成员鸭子面 ─────────────────────────────────────────────────

    async def chat(self, user_input: str, *, stream: bool = True, session_id: Optional[str] = None, metadata: Optional[dict] = None, **_ignored) -> dict:
        # swarm._run_member 的签名约束（swarm.py:2256-2259）：不接受 temperature/max_tokens。
        emitter = (metadata or {}).get("event_emitter")
        if session_id:
            self.current_session_id = session_id
        # B1：捕获本轮回环——泵线程的权限裁决要经它桥回审批链。
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        context = NeuacpSessionContext(
            member_session_id=self.current_session_id or "",
            task_text=user_input,
            cwd=self._cwd,
            permission_mode="chain",
            metadata=dict(metadata or {}),
        )
        await self._executor.start(context)
        result = await self._executor.prompt(user_input, emitter, self._permission_asker)
        return {"text": result.text}

    async def cancel(self) -> None:
        await self._executor.cancel()

    async def close(self) -> None:
        await self._executor.close()
