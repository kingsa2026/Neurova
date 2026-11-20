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
import logging
from typing import Any, Callable, List, Optional

from neurova.agent.neuacp.acp_client import NeuacpClient, NeuacpError
from neurova.agent.neuacp.executor import NeuacpExecResult, NeuacpSessionContext

logger = logging.getLogger(__name__)


class NeuacpStdioExecutor:
    """绑定一个外部代理子进程；每次 prompt 对应一个 ACP session。

    P1 移交清偿（进程池接入）：经 :meth:`attachProcessPool` 挂上
    NeuacpProcessPool 后，start 从池 acquire 已握手进程（键含租户段）、
    prompt 复用、close 归还（池负责空闲回收/上限排队/崩溃踢出）；池侧
    异常一律 fail-open 退回直启，不阻断派活。未接池保持直启行为。
    """

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
        self._command = [str(part) for part in command]
        self._env_extra = dict(env_extra or {})
        self._request_timeout = request_timeout
        self._prompt_timeout = prompt_timeout
        self._on_tool_call = on_tool_call
        self._emitter: Optional[Callable[[str, Any], None]] = None
        self._permission_asker: Optional[Callable[[str, str, str], dict]] = None
        self._session_id: Optional[str] = None
        self._text_buffer = ""
        self._crash_reason: Optional[str] = None
        # P1 移交清偿：进程池挂载点（attachProcessPool 注入；None = 直启）
        self._pool: Optional[Any] = None
        self._pool_key: Optional[tuple] = None
        self._pool_entry: Optional[Any] = None
        # F2 帧留痕键（§3.2/F5）：start(ctx) 时从 metadata["subagent_id"] 取；
        # 未绑定（空）一律不落盘——无主会话（如管理面 /test）不留痕。
        self._frame_key: Optional[str] = None
        self._client = self._newClient()

    # ---------- NeuacpExecutor 协议 ----------

    def attachProcessPool(self, pool: Any, pool_key: tuple) -> None:
        """挂载进程池（swarm._resolveExternalMember 装配期调用）。

        ``pool`` 需提供 ``acquire(key, factory)`` / ``release(key, entry)``
        鸭子面（NeuacpProcessPool 满足）；``pool_key`` 为含租户段的池键。
        """
        self._pool = pool
        self._pool_key = tuple(pool_key)

    async def start(self, ctx: NeuacpSessionContext) -> None:
        self._session_id = None
        self._text_buffer = ""
        self._crash_reason = None
        if ctx.cwd:
            self._cwd = ctx.cwd
        self._frame_key = str((ctx.metadata or {}).get("subagent_id") or "").strip() or None
        # 幂等：已启动（握手完成且进程存活）则复用同一进程，不重复 initialize。
        await asyncio.to_thread(self._ensureClient)
        # 池复用件每次 start 重设帧留痕键（随取用方切换；无主=空键不留痕）。
        self._applyFrameKey()

    def _applyFrameKey(self) -> None:
        """把本执行体的帧留痕键绑到生效中的 ACP 客户端（fail-open）。"""
        client = self._client
        if client is None:
            return
        try:
            client.setFrameKey(self._frame_key)
        except Exception as exc:  # noqa: BLE001 - 绑定失败不阻断派活
            logger.debug("帧留痕键绑定失败（fail-open）: %s", exc)

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
        entry, self._pool_entry = self._pool_entry, None
        if entry is not None and self._pool is not None:
            # 池路径：归还进程（池负责复用/空闲回收/崩溃踢出），不直接 terminate。
            # release 是同步记账（健康件驻留不阻塞；死件才走 terminate）。
            try:
                self._pool.release(self._pool_key, entry)
            except Exception as exc:  # noqa: BLE001 - 归还失败兜底直关（防进程泄漏）
                logger.warning("外部进程归还失败，兜底关闭 (key=%s): %s", self._pool_key, exc)
                await asyncio.to_thread(self._client.terminate)
            # 复位为未启动客户端：防止归还被复用进程后本执行体残留旧引用。
            self._client = self._newClient()
            return
        await asyncio.to_thread(self._client.terminate)

    # ---------- 内部 ----------

    def _ensureClient(self) -> None:
        """确保底层 ACP 客户端就绪（幂等）：优先池取件，池故障 fail-open 直启。"""
        if self._client.started:
            return
        if self._pool is not None and self._pool_key is not None:
            try:
                entry = self._pool.acquire(self._pool_key, self._newStartedClient)
            except Exception as exc:  # noqa: BLE001 - fail-open：池异常不阻断派活
                logger.warning("外部进程池获取失败，退回直启 (key=%s): %s", self._pool_key, exc)
            else:
                self._pool_entry = entry
                self._client = entry.process
                self._bindClientCallbacks(self._client)
                return
        # 直启（未接池或池故障退回）：当前件已死/未启动则换新件拉起。
        if not self._client.started:
            self._client = self._newStartedClient()

    def _newClient(self) -> NeuacpClient:
        """构造未启动的 ACP 客户端（回调/权限处理器随本执行体绑定）。"""
        client = NeuacpClient(
            self._command,
            cwd=self._cwd,
            env_extra=self._env_extra,
            on_event=self._onEvent,
            on_crash=self._onCrash,
            request_timeout=self._request_timeout,
        )
        client.setRequestHandler("session/request_permission", self._handlePermissionRequest)
        # 构造期即绑帧留痕键：直启路径的 initialize 握手帧也归入本 run 的帧流
        # （start(ctx) 已先设 self._frame_key）；池复用件随后由 _applyFrameKey 重绑。
        if self._frame_key:
            client.setFrameKey(self._frame_key)
        return client

    def _newStartedClient(self) -> NeuacpClient:
        """构造并拉起一个 ACP 客户端（池 factory 与直启路径共用）。"""
        client = self._newClient()
        client.start()
        return client

    def _bindClientCallbacks(self, client: NeuacpClient) -> None:
        """池复用件回调重绑：事件/崩溃/权限裁决随本次取用方执行体。"""
        try:
            client.setEventHandlers(on_event=self._onEvent, on_crash=self._onCrash)
            client.setRequestHandler("session/request_permission", self._handlePermissionRequest)
        except Exception as exc:  # noqa: BLE001 - 重绑失败不影响已持有的可用回调
            logger.debug("池复用件回调重绑失败（沿用原回调）: %s", exc)

    def setToolCallHandler(self, handler: Optional[Callable[[dict], None]]) -> None:
        """注册 tool_call(_update) 镜像回调（B2：适配器经此接入轨迹/账本）。

        handler 收到的是 ACP update dict 原样透传；传 None 注销。
        """
        self._on_tool_call = handler

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
        toolName = tool.get("title") or tool.get("toolCallId") or "unknown"
        # B1（§4.4）：action 命名空间 acp:{tool}:{kind}；kind 为 ACP 工具调用
        # 类别（read/edit/delete/move/search/execute/think/fetch/other），
        # 未声明按 other（审批档由适配器按 kind 声明、链内危险正则统一升档）。
        kind = str(tool.get("kind") or "other")
        action = f"acp:{toolName}:{kind}"
        try:
            decision = asker(action, str(params.get("reason") or ""), json.dumps(params, ensure_ascii=False))
        except Exception:
            return {"outcome": {"choice": "deny"}}
        approved = bool((decision or {}).get("approved"))
        return {"outcome": {"choice": "allow" if approved else "deny"}}
