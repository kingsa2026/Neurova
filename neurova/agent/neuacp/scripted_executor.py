# -*- coding: utf-8 -*-
"""NeuacpScriptedExecutor：内核级同构桩（F4）。测试支撑/确定性回归用，无子进程无二进制。

与 NeuacpStdioExecutor / NeuacpPluginExecutor 实现**同一协议**
（executor.py:36-49：async start/prompt/cancel/close + setToolCallHandler +
attachProcessPool（no-op）+ setFrameKey）。以声明式剧本驱动 prompt：每步产出
与真执行体**同构**的帧（经 frame_log 留痕；帧写入 fail-open——frame_key 未设
或 frame_log 并行交付期暂不可用一律跳过，绝不因帧失败阻断执行）。

剧本步骤（list[dict]，逐条消费）：
  {"emit": ["content"|"reasoning", text]}  产出 chunk；content 累积进结果文本；
                                           帧形与 ACP wire 同构（session_update 的
                                           agent_message_chunk|agent_thought_chunk）。
  {"tool_call": {...}}                     送达 setToolCallHandler 注册的镜像 handler
                                           （未注册忽略）；帧 = session_update/tool_call
                                           + 步骤原样展开。
  {"request_permission": {...}}            同步裁决（action/reason/context 取步骤键，
                                           缺省 acp:demo:edit/""/scripted）；in 请求帧
                                           + out 应答帧；裁决拒绝 → 跳过剩余步骤，
                                           以 stop_reason="cancelled" 收（已累积文本
                                           仍返回）。未注册裁决方或裁决异常一律
                                           deny（与真执行体 fail-closed 同纪律）。
  {"result": {"stopReason": ..., ...}}     设 raw 与 stop_reason；帧 = 步骤原样。
  {"crash": reason}                        observed 崩溃帧后抛 NeuacpError（诚实失败）。
  {"exit_code": n}                         n 非 0 → 抛 NeuacpError（诚实失败）。
  {"sleep": 秒}                             可被 cancel() 中止的等待；中止后跳过剩余
                                           步骤，以 stop_reason="cancelled" 收。

定位：既有 wire 桩（真子进程）测传输层本身；本桩测传输层**之上**的全部语义——
上层（adapter/账本/投影）回归无二进制化。
"""
import asyncio
from typing import Any, Callable, List, Optional

from neurova.agent.neuacp.acp_client import NeuacpError
from neurova.agent.neuacp.executor import NeuacpExecResult, NeuacpSessionContext

_SLEEP_POLL_INTERVAL_S = 0.05
_DEFAULT_PERMISSION_ACTION = "acp:demo:edit"
_DEFAULT_PERMISSION_CONTEXT = "scripted"


class NeuacpScriptedExecutor:
    """剧本驱动的外部执行体替身：与真执行体同一协议、同构帧流。"""

    def __init__(
        self,
        command: Optional[List[str]] = None,
        *,
        script: Optional[List[dict]] = None,
        cwd: str = "",
    ) -> None:
        # command 仅作协议同形保留（无子进程，不消费）。
        self._command = [str(part) for part in command] if command else []
        self._script = [step for step in (script or []) if isinstance(step, dict)]
        self._cwd = cwd or ""
        self._on_tool_call: Optional[Callable[[dict], None]] = None
        self._permission_asker: Optional[Callable[[str, str, str], dict]] = None
        self._frame_key = ""
        self._frame_key_explicit = False
        # 运行态（每次 start 复位，可重入）。
        self._text_buffer = ""
        self._stop_reason = "end_of_turn"
        self._raw: Optional[dict] = None
        self._cancel_requested = False

    # ---------- NeuacpExecutor 协议 ----------

    async def start(self, ctx: NeuacpSessionContext) -> None:
        """与真执行体同语义：每次 start 复位运行态，可重入。"""
        self._text_buffer = ""
        self._stop_reason = "end_of_turn"
        self._raw = None
        self._cancel_requested = False
        if ctx.cwd:
            self._cwd = ctx.cwd
        if not self._frame_key_explicit:
            metadata = getattr(ctx, "metadata", None) or {}
            self._frame_key = str(metadata.get("subagent_id") or "")

    async def prompt(
        self,
        task_text: str,
        emitter: Callable[[str, Any], None],
        on_permission: Callable[[str, str, str], dict],
    ) -> NeuacpExecResult:
        self._permission_asker = on_permission
        self._text_buffer = ""
        self._stop_reason = "end_of_turn"
        self._raw = None
        for step in self._script:
            if self._cancel_requested:
                return self._cancelledResult()
            early = await self._runStep(step, emitter)
            if early is not None:
                return early
        return NeuacpExecResult(text=self._text_buffer, stop_reason=self._stop_reason, raw=self._raw)

    async def cancel(self) -> None:
        self._cancel_requested = True

    async def close(self) -> None:
        """无子进程资源：close 幂等 no-op（协议同形）。"""
        return None

    # ---------- 协议配套挂点 ----------

    def setToolCallHandler(self, handler: Optional[Callable[[dict], None]]) -> None:
        """注册 tool_call 镜像回调（与 NeuacpStdioExecutor 同名同语义）；传 None 注销。"""
        self._on_tool_call = handler

    def attachProcessPool(self, pool: Any, pool_key: tuple) -> None:
        """无子进程：进程池挂载为 no-op（保持协议同形，供装配层统一调用）。"""
        return None

    def setFrameKey(self, key) -> None:
        """显式绑定帧账本键；设置后 start(ctx) 不再从 metadata 覆盖。"""
        self._frame_key = str(key or "")
        self._frame_key_explicit = True

    # ---------- 剧本步骤 ----------

    async def _runStep(self, step: dict, emitter: Callable[[str, Any], None]) -> Optional[NeuacpExecResult]:
        """执行单步；返回非 None 表示提前收尾（deny/cancel）。未知步骤宽容忽略。"""
        if "emit" in step:
            self._runEmitStep(step["emit"], emitter)
        elif "tool_call" in step:
            self._runToolCallStep(step)
        elif "request_permission" in step:
            return self._runPermissionStep(step)
        elif "result" in step:
            self._runResultStep(step)
        elif "crash" in step:
            self._runCrashStep(step)
        elif "exit_code" in step:
            self._runExitCodeStep(step)
        elif "sleep" in step:
            return await self._runSleepStep(step)
        return None

    def _runEmitStep(self, payload: Any, emitter: Callable[[str, Any], None]) -> None:
        if not isinstance(payload, (list, tuple)) or len(payload) < 2:
            return
        kind = str(payload[0] or "")
        text = payload[1]
        # 与 wire 侧同纪律：空文本 chunk 整体丢弃（不回调、不累积、不留帧）。
        if kind not in ("content", "reasoning") or not text:
            return
        if kind == "content":
            self._text_buffer += str(text)
        if emitter is not None:
            try:
                emitter(kind, text)
            except Exception:
                pass
        self._appendFrameSafe("in", {
            "type": "session_update",
            "sessionUpdate": "agent_message_chunk" if kind == "content" else "agent_thought_chunk",
            "content": {"text": text},
        })

    def _runToolCallStep(self, step: dict) -> None:
        update = step.get("tool_call")
        if not isinstance(update, dict):
            update = {}
        handler = self._on_tool_call
        if handler is not None:
            try:
                handler(update)
            except Exception:
                pass
        self._appendFrameSafe("in", {"type": "session_update", "sessionUpdate": "tool_call", **step})

    def _runPermissionStep(self, step: dict) -> Optional[NeuacpExecResult]:
        payload = step.get("request_permission")
        if not isinstance(payload, dict):
            payload = {}
        action = str(payload.get("action") or _DEFAULT_PERMISSION_ACTION)
        reason = str(payload.get("reason") or "")
        context = str(payload.get("context") or _DEFAULT_PERMISSION_CONTEXT)
        self._appendFrameSafe("in", {"type": "permission_request", **payload})
        approved = self._resolvePermission(action, reason, context)
        self._appendFrameSafe("out", {"type": "permission_response", "approved": bool(approved)})
        if not approved:
            # deny：中止剩余步骤，以 cancelled 收尾（已累积文本仍返回）。
            return self._cancelledResult()
        return None

    def _resolvePermission(self, action: str, reason: str, context: str) -> bool:
        asker = self._permission_asker
        if asker is None:
            return False  # 与真执行体同纪律：未注册裁决方一律 deny（fail-closed）
        try:
            decision = asker(action, reason, context)
        except Exception:
            return False
        return bool((decision or {}).get("approved"))

    def _runResultStep(self, step: dict) -> None:
        payload = step.get("result")
        if not isinstance(payload, dict):
            payload = {}
        self._raw = payload
        self._stop_reason = str(payload.get("stopReason") or "end_of_turn")
        self._appendFrameSafe("in", step)

    def _runCrashStep(self, step: dict) -> None:
        reason = str(step.get("crash") or "")
        self._appendFrameSafe("observed", {"type": "crashed", "reason": reason})
        raise NeuacpError(f"external agent crashed during prompt: {reason}")

    def _runExitCodeStep(self, step: dict) -> None:
        try:
            code = int(step.get("exit_code"))
        except (TypeError, ValueError):
            return
        if code != 0:
            raise NeuacpError(f"scripted executor exited with code {code}")

    async def _runSleepStep(self, step: dict) -> Optional[NeuacpExecResult]:
        try:
            seconds = float(step.get("sleep") or 0)
        except (TypeError, ValueError):
            seconds = 0.0
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, seconds)
        while not self._cancel_requested:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(_SLEEP_POLL_INTERVAL_S, remaining))
        if self._cancel_requested:
            return self._cancelledResult()
        return None

    # ---------- 内部 ----------

    def _cancelledResult(self) -> NeuacpExecResult:
        return NeuacpExecResult(text=self._text_buffer, stop_reason="cancelled", raw=self._raw)

    def _appendFrameSafe(self, direction: str, frame: dict) -> None:
        """帧留痕：fail-open，绝不因帧失败阻断执行。

        frame_log 由并行线同期交付——惰性 import；frame_key 未设（无主不留痕）
        或模块/写盘暂不可用（ImportError 及一切运行期异常）时跳过写入。
        """
        key = self._frame_key
        if not key:
            return
        try:
            from neurova.agent.neuacp.frame_log import appendFrame  # 惰性 import（并行交付）

            appendFrame(key, direction, frame)
        except (ImportError, Exception):  # noqa: BLE001 - ImportError=模块缺席；Exception=写盘故障
            return
