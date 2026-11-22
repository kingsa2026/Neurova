# -*- coding: utf-8 -*-
"""NeuacpStdioExecutor：以 ACP（v1 / v2）驱动一个外部编码代理子进程。

事件映射（设计文档 §4.4）：session/update 的 agent_message_chunk →
emitter("content")、agent_thought_chunk → emitter("reasoning")、
tool_call(_update) → on_tool_call 镜像（B2 接轨迹/账本）；
session/request_permission → on_permission 同步裁决（B1 接审批链），
未注册或裁决异常一律 deny（fail-closed）。

G6（v2 适配）：握手协商出 v2 时经 codec_v2 分发——出站形状（info 握手、
内容块 prompt、$/cancel_request 按 requestId 取消）与入站 24 分支归一化
（见 codec_v2.parseSessionUpdate）都收口在 codec；本模块只做内部事件路由，
v1 线上路径保持逐字节不变。v2 语义差异：session/prompt 应答只是插入回执
（messageId），回合完成以 state_update(idle, stopReason) 为准。
"""
import asyncio
import json
import logging
import threading
from typing import Any, Callable, List, Optional

from neurova.agent.neuacp.acp_client import NeuacpClient, NeuacpError, NeuacpTimeoutError
from neurova.agent.neuacp.codec_v2 import V2ProtocolError, parseSessionUpdate
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
        protocol_version: str = "1",
        run_tenant_id: str = "",
    ) -> None:
        self._cwd = cwd or ""
        self._command = [str(part) for part in command]
        self._env_extra = dict(env_extra or {})
        self._request_timeout = request_timeout
        self._prompt_timeout = prompt_timeout
        self._on_tool_call = on_tool_call
        # G1：目录条目声明的 ACP 协议版本（缺省 "1" 行为不变）；create client
        # 时传入 start 按声明版本协商（registry 声明 v2 的 agent 走 v2 握手）。
        self._protocol_version = str(protocol_version or "1")
        # C4：run 级凭据的租户段（swarm 装配期传入；run id 在 start(ctx) 时从
        # metadata 取）——两者合成 run 级身份凭据注入子进程环境。
        self._run_tenant_id = str(run_tenant_id or "")
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
        # G6：v2 回合收口等待（state_update idle）与捕获的停止原因。
        self._stop_reason: Optional[str] = None
        self._turn_wait: Optional[threading.Event] = None
        self._client = self._newClient()

    # ---------- NeuacpExecutor 协议 ----------

    def attachProcessPool(self, pool: Any, pool_key: tuple, ownerId: str = "") -> None:
        """挂载进程池（swarm._resolveExternalMember 装配期调用）。

        ``pool`` 需提供 ``acquire(key, factory)`` / ``release(key, entry)``
        鸭子面（NeuacpProcessPool 满足）；``pool_key`` 为含租户段的池键。
        ``ownerId``（W4）：swarm 成员 id——装配期追加为池键属主尾段
        （<既有六段>│<ownerId>），spawn 登记行 ownerId 随之补全；缺省空 =
        无属主装配（管理面等），保持旧键六段形态。
        """
        self._pool = pool
        try:
            from neurova.agent.neuacp.process_pool import poolKeyWithOwner

            self._pool_key = poolKeyWithOwner(tuple(pool_key), ownerId)
        except Exception as exc:  # noqa: BLE001 - 键整形失败退回原键（acquire 侧再归一）
            logger.debug("池键属主段追加失败，退回原键 (ownerId=%s): %s", ownerId, exc)
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
        # C4：凭据上下文须在 _ensureClient 之后绑——ensure 可能新建 client 实例。
        self._applyRunCredentialContext()

    def _applyRunCredentialContext(self) -> None:
        """C4：把 run 级身份凭据上下文绑到生效中的客户端（fail-open）。

        凭据=HMAC(run_id+tenant_id) 的作用域令牌，子进程经环境变量拿到可证明
        自身归属的凭据。池复用件的进程环境在首启定格——run 级 env 凭据对
        复用进程的后续 run 不再生效（HTTP 消费面卡需按池化语义另行裁定）。
        """
        subagent_id = self._frame_key
        if not subagent_id or not self._run_tenant_id:
            return
        try:
            self._client.setRunCredentialContext(
                {"run_id": subagent_id, "tenant_id": self._run_tenant_id})
        except Exception as exc:  # noqa: BLE001 - 凭据注入失败不阻断启动
            logger.debug("run 凭据上下文注入失败（忽略）: %s", exc)

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
        # G6：v2 会话经 codec 分发（应答为 messageId 回执、完成以 idle 为准）；
        # v1 走既有路径（线上逐字节不变）。
        codec = self._client.codec
        if codec is not None:
            return await self._promptV2(task_text, codec)
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

    async def _promptV2(self, task_text: str, codec: Any) -> NeuacpExecResult:
        """v2 回合：session/prompt 应答只是插入回执（messageId），回合完成以
        state_update(idle, stopReason) 为准——发完 prompt 后等 idle 再收口。

        这是 v2 协议语义变化（完成信号从应答移到通知），不是行为改写；
        停止原因缺省 end_of_turn，与 v1 的缺省口径一致。
        """
        session = await asyncio.to_thread(
            self._client.request, "session/new", codec.newSessionParams(self._cwd)
        )
        try:
            session = codec.parseNewSessionResponse(session)
        except V2ProtocolError as exc:
            raise NeuacpError(f"external agent invalid session/new response: {exc}") from exc
        self._session_id = session["sessionId"]
        # 就绪旗标在发出 prompt 前武装；此后到达的当前会话 idle 才是本回合
        # 收口。（v2 规定新会话缺省 idle、无需先导 state_update，武装窗口内
        # 理论上可能混入的初始 idle 快照按「回合未开始」忽略——见 _onEventV2
        # 的 sessionId 过滤。）
        self._stop_reason = None
        turn_wait = threading.Event()
        self._turn_wait = turn_wait
        try:
            ack = await asyncio.to_thread(
                self._client.request, "session/prompt",
                codec.promptParams(self._session_id, task_text), self._prompt_timeout,
            )
        except NeuacpError:
            self._turn_wait = None
            if self._crash_reason:
                raise NeuacpError(f"external agent crashed during prompt: {self._crash_reason}") from None
            raise
        try:
            ack = codec.parsePromptResponse(ack)
        except V2ProtocolError as exc:
            self._turn_wait = None
            raise NeuacpError(f"external agent invalid prompt response: {exc}") from exc
        wait_s = self._prompt_timeout if self._prompt_timeout is not None else self._request_timeout
        # 阻塞等待必须挪出事件循环线程（to_thread）：否则等 idle 期间整个
        # loop 被卡死——cancel()/emitter 等一切协程都无法推进。
        finished = await asyncio.to_thread(turn_wait.wait, wait_s)
        self._turn_wait = None
        if not finished:
            raise NeuacpTimeoutError("ACP v2 prompt timeout: 等待 state_update idle 超时")
        if self._crash_reason:
            raise NeuacpError(f"external agent crashed during prompt: {self._crash_reason}")
        stop_reason = self._stop_reason or "end_of_turn"
        return NeuacpExecResult(
            text=self._text_buffer,
            stop_reason=str(stop_reason),
            raw={"messageId": ack.get("messageId"), "stopReason": stop_reason},
        )

    async def cancel(self) -> None:
        codec = self._client.codec
        if codec is not None:
            # G6：v2 按 requestId 取消在途回合（$/cancel_request 通知）。
            request_id = self._client.lastRequestId()
            if request_id is not None and self._client.is_alive:
                try:
                    await asyncio.to_thread(
                        self._client.notify, codec.cancel_method,
                        codec.cancelRequestParams(request_id),
                    )
                except NeuacpError:
                    pass
            return
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
        """确保底层 ACP 客户端就绪（幂等）：优先池取件（有界等待，M10），
        池设施故障 fail-open 直启；池的明确裁决（池满超时/已关闭）如实上抛。"""
        if self._client.started:
            return
        if self._pool is not None and self._pool_key is not None:
            from neurova.agent.neuacp.process_pool import envAcquireWaitTimeout

            try:
                entry = self._pool.acquire(self._pool_key, self._newStartedClient,
                                           waitTimeout=envAcquireWaitTimeout())
            except NeuacpError:
                # M10：池满超时/池已关闭是池的明确裁决——直启会绕过全局进程上限，
                # 必须结构化失败上抛，由 run 链诚实记失败（不静默重试）。
                raise
            except Exception as exc:  # noqa: BLE001 - fail-open：池设施异常不阻断派活
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
        # G1：initialize 按条目声明版本协商（缺省 "1" 与既有 v1 全量一致）。
        client.start(protocol_version=self._protocol_version)
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
        # G6：v2 回合在等 idle 时崩溃——唤醒等待线程，走 crash 诚实上抛路径。
        wait = self._turn_wait
        if wait is not None:
            wait.set()

    def _onEvent(self, method: str, params: dict) -> None:
        if method != "session/update":
            return
        # G6：v2 会话经 codec 归一化 24 分支后路由；v1 走既有分支名（不变）。
        if self._client.codec is not None:
            self._onEventV2(params)
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

    def _onEventV2(self, params: dict) -> None:
        """v2 session/update → 内部事件路由（codec 归一化后的单一形状）。

        content/reasoning → emitter 流式（并累积结果文本）；tool_call →
        镜像；stop → 记录停止原因并唤醒回合等待；message/plan/usage/
        compaction/skip 本仓暂无消费面——按「未知类型跳过」纪律归档
        （debug 留痕），不臆造下游事件。
        """
        update_session = params.get("sessionId")
        if isinstance(update_session, str) and update_session and update_session != self._session_id:
            return  # 非当前会话的更新（旧会话残留/多会话进程）不消费
        event = parseSessionUpdate(params)
        kind = event.get("event")
        if kind == "content":
            text = event.get("text") or ""
            if not text:
                return
            self._text_buffer += text
            emitter = self._emitter
            if emitter is not None:
                try:
                    emitter("content", text)
                except Exception:
                    pass
        elif kind == "reasoning":
            text = event.get("text") or ""
            if not text:
                return
            emitter = self._emitter
            if emitter is not None:
                try:
                    emitter("reasoning", text)
                except Exception:
                    pass
        elif kind == "tool_call":
            if self._on_tool_call is not None:
                try:
                    self._on_tool_call(event.get("update") or {})
                except Exception:
                    pass
        elif kind == "stop":
            stop_reason = event.get("stopReason") or ""
            if stop_reason:
                self._stop_reason = stop_reason
            wait = self._turn_wait
            if wait is not None:
                wait.set()
        else:
            logger.debug(
                "neuacp v2 update 归档不消费: event=%s type=%s reason=%s",
                kind, (event.get("update") or {}).get("sessionUpdate"),
                event.get("reason"),
            )

    def _permissionDenyResponse(self, params: dict) -> dict:
        """fail-closed 拒绝应答（按协商版本选线上形状）。"""
        codec = self._client.codec
        if codec is not None:
            return codec.permissionResponse({"approved": False}, params)
        return {"outcome": {"choice": "deny"}}

    def _handlePermissionRequest(self, params: dict, respond) -> None:
        """session/request_permission 处理器（M9 契约：泵线程调用，**不阻塞**）。

        裁决挪到独立工作线程——人审等待期间泵线程继续派发流式 chunk/心跳/
        崩溃通知；裁决完成后经 ``respond`` 补发应答帧（JSON-RPC 按 id 配对，
        允许晚于其它帧到达）。asker 未注册/异常一律 fail-closed deny。
        """
        codec = self._client.codec
        asker = self._permission_asker

        def _deny() -> None:
            respond(self._permissionDenyResponse(params))

        if asker is None:
            _deny()
            return
        if codec is not None:
            # v2：主体在 subject 面包（tool_call/command），标题提至顶层 title。
            subject = params.get("subject") or {}
            tool = subject.get("toolCall") or {} if subject.get("type") == "tool_call" else {}
            toolName = (tool.get("title") or tool.get("name")
                        or params.get("title") or tool.get("toolCallId") or "unknown")
            reason_text = str(params.get("description") or "")
        else:
            tool = params.get("toolCall") or {}
            toolName = tool.get("title") or tool.get("toolCallId") or "unknown"
            reason_text = str(params.get("reason") or "")
        # B1（§4.4）：action 命名空间 acp:{tool}:{kind}；kind 为 ACP 工具调用
        # 类别（read/edit/delete/move/search/execute/think/fetch/other），
        # 未声明按 other（审批档由适配器按 kind 声明、链内危险正则统一升档）。
        kind = str(tool.get("kind") or "other")
        action = f"acp:{toolName}:{kind}"

        def _askWorker() -> None:
            try:
                decision = asker(action, reason_text, json.dumps(params, ensure_ascii=False))
            except Exception:
                _deny()
                return
            approved = bool((decision or {}).get("approved"))
            try:
                if codec is not None:
                    respond(codec.permissionResponse(decision, params))
                else:
                    respond({"outcome": {"choice": "allow" if approved else "deny"}})
            except Exception:
                _deny()

        threading.Thread(target=_askWorker, daemon=True,
                         name=f"neuacp-permission-{toolName}").start()
