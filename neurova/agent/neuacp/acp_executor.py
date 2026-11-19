# -*- coding: utf-8 -*-
"""NeuacpStdioExecutor：以 ACP v1 驱动一个外部编码代理子进程。

事件映射（设计文档 §4.4）：session/update 的 agent_message_chunk →
emitter("content")、agent_thought_chunk → emitter("reasoning")、
tool_call(_update) → on_tool_call 镜像（B2 接轨迹/账本）；
session/request_permission → on_permission 同步裁决（B1 接审批链），
未注册或裁决异常一律 deny（fail-closed）。
"""
import asyncio
import json
from typing import Any, Callable, List, Optional

from neurova.agent.neuacp.acp_client import NeuacpClient, NeuacpError
from neurova.agent.neuacp.executor import NeuacpExecResult, NeuacpSessionContext


class NeuacpStdioExecutor:
    """绑定一个外部代理子进程；每次 prompt 对应一个 ACP session。"""

    def __init__(
        self,
        command: List[str],
        *,
        cwd: Optional[str] = None,
        env_extra: Optional[dict] = None,
        request_timeout: float = 30.0,
        prompt_timeout: Optional[float] = None,
        on_tool_call: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self._cwd = cwd or ""
        self._prompt_timeout = prompt_timeout
        self._on_tool_call = on_tool_call
        self._emitter: Optional[Callable[[str, Any], None]] = None
        self._permission_asker: Optional[Callable[[str, str, str], dict]] = None
        self._session_id: Optional[str] = None
        self._text_buffer = ""
        self._crash_reason: Optional[str] = None
        self._client = NeuacpClient(
            command,
            cwd=cwd,
            env_extra=env_extra,
            on_event=self._onEvent,
            on_crash=self._onCrash,
            request_timeout=request_timeout,
        )
        self._client.setRequestHandler("session/request_permission", self._handlePermissionRequest)

    # ---------- NeuacpExecutor 协议 ----------

    async def start(self, ctx: NeuacpSessionContext) -> None:
        self._session_id = None
        self._text_buffer = ""
        self._crash_reason = None
        if ctx.cwd:
            self._cwd = ctx.cwd
        await asyncio.to_thread(self._client.start)

    async def prompt(self, task_text: str, emitter: Callable[[str, Any], None], on_permission: Callable[[str, str, str], dict]) -> NeuacpExecResult:
        self._emitter = emitter
        self._permission_asker = on_permission
        self._text_buffer = ""
        self._crash_reason = None
        session = await asyncio.to_thread(
            self._client.request, "session/new", {"cwd": self._cwd, "mcpServers": []}
        )
        self._session_id = session.get("sessionId")
        params = {
            "sessionId": self._session_id,
            "prompt": [{"type": "text", "text": task_text}],
        }
        try:
            result = await asyncio.to_thread(self._client.request, "session/prompt", params, self._prompt_timeout)
        except NeuacpError:
            if self._crash_reason:
                raise NeuacpError(f"external agent crashed during prompt: {self._crash_reason}") from None
            raise
        return NeuacpExecResult(
            text=self._text_buffer,
            stop_reason=str((result or {}).get("stopReason", "end_of_turn")),
            raw=result,
        )

    async def cancel(self) -> None:
        if self._session_id and self._client.is_alive:
            try:
                await asyncio.to_thread(self._client.notify, "session/cancel", {"sessionId": self._session_id})
            except NeuacpError:
                pass

    async def close(self) -> None:
        await asyncio.to_thread(self._client.terminate)

    # ---------- 内部 ----------

    def _onCrash(self, reason: str) -> None:
        self._crash_reason = reason

    def _onEvent(self, method: str, params: dict) -> None:
        if method != "session/update":
            return
        update = params.get("update") or {}
        kind = update.get("sessionUpdate")
        if kind in ("agent_message_chunk", "agent_thought_chunk"):
            text = (update.get("content") or {}).get("text") or ""
            if not text:
                return
            if kind == "agent_message_chunk":
                self._text_buffer += text
                event = "content"
            else:
                event = "reasoning"
            emitter = self._emitter
            if emitter is not None:
                try:
                    emitter(event, text)
                except Exception:
                    pass
        elif kind in ("tool_call", "tool_call_update") and self._on_tool_call is not None:
            try:
                self._on_tool_call(update)
            except Exception:
                pass

    def _handlePermissionRequest(self, params: dict) -> dict:
        asker = self._permission_asker
        if asker is None:
            return {"outcome": {"choice": "deny"}}
        tool = params.get("toolCall") or {}
        action = tool.get("title") or tool.get("toolCallId") or "unknown"
        try:
            decision = asker(action, str(params.get("reason") or ""), json.dumps(params, ensure_ascii=False))
        except Exception:
            return {"outcome": {"choice": "deny"}}
        approved = bool((decision or {}).get("approved"))
        return {"outcome": {"choice": "allow" if approved else "deny"}}
