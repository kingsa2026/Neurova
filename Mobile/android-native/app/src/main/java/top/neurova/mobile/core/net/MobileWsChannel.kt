package top.neurova.mobile.core.net

import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import top.neurova.mobile.core.protocol.ApprovalCard
import top.neurova.mobile.core.protocol.DeviceBridgeEvents
import top.neurova.mobile.core.protocol.DeviceCommand
import top.neurova.mobile.core.protocol.HostConfirmationCard
import top.neurova.mobile.core.protocol.MobileWsClosePolicy
import top.neurova.mobile.core.protocol.ToolActionEvents
import top.neurova.mobile.core.protocol.TunnelTokenSigner

/**
 * 移动 WS 通道（手机客户端设计方案 §5.3；对齐鸿蒙 WebSocketAdapter 语义）：
 * - 握手：一次性 connect_ticket 走 **Authorization: Bearer** 头（后端 _ticketFromHandshake
 *   的优先通道，鸿蒙同款）。子协议 `neurova.auth.<ticket>` 形态已证伪——ticket 含冒号，
 *   不是合法 RFC6455 子协议 token，握手必败（2026-11-16 wsprobe 实测），勿回潮；
 * - 心跳：30s 应用层 ping/pong，帧契约 `{"type":"ping"}` / `{"type":"pong"}`（与后端
 *   mobile_pairing.py 消息循环、鸿蒙 WebSocketAdapter 三方同源）；pong 超时 10s 视为断流
 *   （中继上静默断流没有 close 帧）；
 * - 关闭分档：由 MobileWsClosePolicy 裁决——4001 先续签重试一次（唯一需重新配对的是
 *   续签被拒 device_deregistered）；4008 不重连；manual 恒终态；
 * - relay 鉴权新形态（U9/U16）：relay 模式（`/t/<routeId>` 入口）连接建立后**首条**
 *   消息必须是 `auth` 帧（本地签 `nv1:agent` 信封，裸密钥不上线）；直连模式不变。
 */
class MobileWsChannel(
    private val scope: CoroutineScope,
    private val wsUrlProvider: () -> String?,
    private val ticketProvider: () -> String?,
    /** 4001 续签：成功返回新 ticket，失败抛出（= 设备已解除，终态） */
    private val refreshTicket: suspend () -> String,
    /**
     * U9/U16 relay 鉴权新形态：relay 模式（/t/<routeId> 入口）连接后首条消息必须是
     * `auth` 帧。裸密钥由此提供（移动数据面现取配对 connect_ticket），本地签成
     * `nv1:agent` 信封后再上线；已是信封则原样用。直连模式不提供、不发 auth 帧。
     */
    private val relayAuthSecretProvider: () -> String? = { null },
    /** 心跳间隔与 pong 超时：生产用常量默认值，测试注入短周期（行为路径同一份） */
    private val heartbeatIntervalMs: Long = HEARTBEAT_MS,
    private val pongTimeoutMs: Long = PONG_TIMEOUT_MS,
    client: OkHttpClient = OkHttpClient(),
) {
    enum class State { IDLE, CONNECTING, AUTHED, REAUTHING, RECONNECTING, FAILED, CLOSED }

    sealed interface Event {
        data class Chunk(val content: String, val sessionId: String) : Event
        data class Done(val sessionId: String, val messageId: String?) : Event
        data class Cancelled(val sessionId: String) : Event
        data class Error(val code: String, val message: String) : Event
        data class AgentSwitched(val agentId: String) : Event

        /** 排队位/让位闸等待/挂起（运行态透明化；position/attempt/waitSeconds/reason 依来源可选） */
        data class Queued(
            val sessionId: String,
            val position: Int? = null,
            val attempt: Int? = null,
            val waitSeconds: Double? = null,
            val reason: String? = null,
            val parked: Boolean = false,
        ) : Event

    /** 管线思考流（reasoning）片段 */
    data class Reasoning(val sessionId: String, val content: String) : Event

    /**
     * 电脑/浏览器操作实时事件（tool_executor._emit_computer_event 单源广播）：
     * 驱动聊天页工具事件卡；needs_host_confirmation / pending_approval 随载荷
     * 到达时另行发 HostConfirmationRequired / ApprovalRequired（同一载荷双卡面）。
     */
    data class ComputerAction(
        val sessionId: String,
        val tool: String,
        val summary: String?,
        val success: Boolean?,
        val payload: JsonObject,
    ) : Event

    /** U1 主机确认卡（needs_host_confirmation）：确认/拒绝调 host-key confirm 接口 */
    data class HostConfirmationRequired(val sessionId: String, val card: HostConfirmationCard) : Event

    /** U6 动态干预审批卡（pending_approval / chat:approval_required）：批准/拒绝调 approvals 接口 */
    data class ApprovalRequired(val sessionId: String, val card: ApprovalCard) : Event

    /**
     * 设备桥命令（device:execute，2026-11-23 计划卡 A2）：由 DeviceBridgeService
     * 的派发器执行并回 device:result；本通道只负责解析与收发，不做执行裁决。
     */
    data class DeviceCommandArrived(val command: DeviceCommand, val frame: JsonObject) : Event
}

    private val json = Json { ignoreUnknownKeys = true }

    private val stateFlow = MutableStateFlow(State.IDLE)
    val state: StateFlow<State> = stateFlow

    private val eventsFlow = MutableSharedFlow<Event>(extraBufferCapacity = 64)
    val events: SharedFlow<Event> = eventsFlow

    private val client = client.newBuilder()
        .pingInterval(0, TimeUnit.SECONDS) // 心跳由应用层驱动，禁用 OkHttp 自动 ping
        .build()

    private var socket: WebSocket? = null
    private var heartbeatJob: Job? = null

    /**
     * U9：本次连接若为 relay 模式，onOpen 后**先发**这条 auth 帧（先于 sync_resume
     * 与心跳——中继/后端对首帧的契约就是 auth）。直连模式恒 null。
     */
    @Volatile
    private var pendingRelayAuthFrame: JsonObject? = null
    /** 本连接已发过 relay auth 帧：用于识别后端 unknown_type 的已知良性回声 */
    @Volatile
    private var sentRelayAuthThisConnection: Boolean = false

    /** 本周期是否仍在等 pong（OkHttp 读线程置 false，心跳协程读；判定超时的唯一依据） */
    private val awaitingPong = AtomicBoolean(false)
    private var reconnectCount = 0
    private var refreshAlreadyTried = false
    private var manualClosed = false

    /**
     * D-5 三端契约对齐：连接契约（服务端 pong 帧 `connection_runtime` 字段，
     * G4 describeForClients 单源）到达后覆盖以下取值；未到达前保持构造缺省
     * （与既有行为一致）。@Volatile：OkHttp 读线程写、心跳/重连协程读。
     */
    @Volatile
    private var activeHeartbeatMs: Long = heartbeatIntervalMs
    @Volatile
    private var activeBackoffBaseMs: Long = DEFAULT_BACKOFF_BASE_MS
    @Volatile
    private var activeBackoffCapMs: Long = DEFAULT_BACKOFF_CAP_MS

    /**
     * D3 出站帧游标：服务端账本单调 seq（先落账再发送）。重连成功且游标 > 0
     * 时发 sync_resume 补拉 (cursor, head] 的帧；收到 sync_snapshot_required
     * 归零（弃游标按首连语义走快照/历史恢复）。内存态：进程重启走会话历史
     * 恢复，不重放旧帧。@Volatile：OkHttp 读线程写、重连协程读。
     */
    @Volatile
    private var lastServerSeq: Long = 0L
    /** D-5 按需订阅范围（缺省 global 全收；session/thread 须带 scopeKey） */
    @Volatile
    private var subscriptionScope: String = "global"
    @Volatile
    private var subscriptionScopeKey: String = ""

    /**
     * D-5 按需订阅：设置订阅范围（看一个线程不付全部线程的账）。
     * scope ∈ session/thread/global；session/thread 须带非空 scopeKey
     * （与服务端 parseSubscriptionScope 同规，非法输入保持原范围不变）。
     * 断线重连的 sync_resume 会自动携带该范围。
     */
    fun setSubscriptionScope(scope: String, scopeKey: String) {
        val normalized = scope.trim().lowercase()
        if (normalized != "session" && normalized != "thread" && normalized != "global") return
        val key = scopeKey.trim()
        if (normalized != "global" && key.isEmpty()) return
        subscriptionScope = normalized
        subscriptionScopeKey = if (normalized == "global") "" else key
    }

    fun connect() {
        // 手动关闭是终态（MobileWsClosePolicy：manual 恒终态）——挂起的重连协程
        // 不得借 connect() 复活已关闭的通道
        if (manualClosed) return
        manualClosed = false
        val url = wsUrlProvider() ?: run { stateFlow.value = State.FAILED; return }
        val ticket = ticketProvider() ?: run { stateFlow.value = State.FAILED; return }
        pendingRelayAuthFrame = buildRelayAuthFrame(url, relayAuthSecretProvider)
        sentRelayAuthThisConnection = false
        stateFlow.value = State.CONNECTING
        socket = client.newWebSocket(buildHandshakeRequest(url, ticket), Listener())
    }

    /** 发送对话帧：chat:send / chat:cancel（§8.3 WS 侧语义） */
    fun sendChat(message: String, sessionId: String? = null, agentId: String? = null): Boolean =
        sendFrame(
            buildJsonObject(
                "type" to "chat:send",
                "content" to message,
                "session_id" to sessionId,
                "agent_id" to agentId,
            ),
        )

    fun cancelChat(sessionId: String): Boolean =
        sendFrame(buildJsonObject("type" to "chat:cancel", "session_id" to sessionId))

    /**
     * 设备桥出站帧（device:hello / device:result / device:event，2026-11-23 计划
     * 卡 A1/A2）：与聊天帧走同一 socket、同一账本游标——不另起第二通道。
     */
    fun sendDeviceFrame(frame: JsonObject): Boolean = sendFrame(frame)

    fun close() {
        manualClosed = true
        heartbeatJob?.cancel()
        pendingRelayAuthFrame = null
        sentRelayAuthThisConnection = false
        socket?.close(1000, "manual")
        socket = null
        stateFlow.value = State.CLOSED
    }

    private fun sendFrame(frame: JsonObject): Boolean = socket?.send(json.encodeToString(JsonObject.serializer(), frame)) ?: false

    /**
     * D3 断线补拉：重连成功且游标 > 0 时请求服务端补发 (cursor, head] 的帧。
     * D-5 按需订阅：非 global 范围随补拉请求下发（服务端只推范围内帧并做
     * 越权防线校验）；缺省 global 不带参数=全量。
     */
    private fun resumeMissedFrames() {
        if (lastServerSeq <= 0) return
        val map = linkedMapOf<String, kotlinx.serialization.json.JsonElement>(
            "type" to JsonPrimitive("sync_resume"),
            "last_seq" to JsonPrimitive(lastServerSeq),
        )
        if (subscriptionScope != "global" && subscriptionScopeKey.isNotEmpty()) {
            map["scope"] = JsonPrimitive(subscriptionScope)
            map["scope_key"] = JsonPrimitive(subscriptionScopeKey)
        }
        sendFrame(JsonObject(map))
    }

    private fun buildJsonObject(vararg pairs: Pair<String, String?>): JsonObject = JsonObject(
        pairs.mapNotNull { (key, value) -> value?.let { key to JsonPrimitive(it) } }.toMap(),
    )

    private fun startHeartbeat() {
        heartbeatJob?.cancel()
        heartbeatJob = scope.launch {
            while (true) {
                delay(activeHeartbeatMs)
                awaitingPong.set(true)
                // 心跳是 JSON 帧 {"type":"ping"}：后端消息循环 json.loads 只吃 JSON，
                // 裸文本 "ping" 会炸掉连接（鸿蒙 WebSocketAdapter 同契约，勿回潮）
                if (!sendFrame(buildJsonObject("type" to "ping"))) break
                // 等 pong：到达即进入下一周期（不把 pongTimeout 硬拼进周期——
                // 否则契约 15s 会被拉长成 interval+10s）；超时仍未到视为断流。
                var waited = 0L
                while (awaitingPong.get() && waited < pongTimeoutMs) {
                    delay(50)
                    waited += 50
                }
                if (awaitingPong.get()) {
                    // 超时未收到 pong：视为断流，主动拆线走传输层重连档。关闭码用线上
                    // 合法的 1000——1006 是 RFC 保留码，OkHttp 发送侧直接抛
                    // IllegalArgumentException（原实现的 close(1006) 从未发出去过，
                    // 心跳协程当场崩死，连接成僵尸）
                    socket?.close(1000, "pong-timeout")
                    socket = null
                    break
                }
            }
        }
    }

    private fun scheduleReconnect(code: Int, reason: String) {
        val decision = MobileWsClosePolicy.decide(
            closeCode = code,
            refreshAlreadyTried = refreshAlreadyTried,
            manualClose = manualClosed,
            reconnectCount = reconnectCount,
        )
        when (decision) {
            MobileWsClosePolicy.Decision.TERMINAL_CLOSED -> stateFlow.value = State.CLOSED
            MobileWsClosePolicy.Decision.TERMINAL_FAILED -> stateFlow.value = State.FAILED
            MobileWsClosePolicy.Decision.GIVE_UP -> {
                stateFlow.value = State.FAILED
                eventsFlow.tryEmit(Event.Error("ws_give_up", reason))
            }
            MobileWsClosePolicy.Decision.REFRESH_AND_RETRY -> scope.launch {
                stateFlow.value = State.REAUTHING
                refreshAlreadyTried = true
                runCatching { refreshTicket() }
                    .onSuccess {
                        reconnectCount = 0
                        connect()
                    }
                    .onFailure {
                        stateFlow.value = State.FAILED
                        eventsFlow.tryEmit(Event.Error("device_deregistered", "配对已解除，请重新扫码"))
                    }
            }
            MobileWsClosePolicy.Decision.RECONNECT -> scope.launch {
                stateFlow.value = State.RECONNECTING
                reconnectCount += 1
                delay(backoffMs(reconnectCount))
                connect()
            }
            null -> stateFlow.value = State.FAILED
        }
    }

    private fun backoffMs(count: Int): Long =
        backoffDelayMs(count, activeBackoffBaseMs, activeBackoffCapMs)

    /**
     * D-5 三端契约对齐：应用服务端下发的连接契约（connection_runtime）——
     * 心跳周期与重连退避 base/cap 从单源契约取值；字段缺失/非法时保持现值
     * （旧后端 pong 无该字段 = 行为零变化）。
     */
    private fun applyConnectionRuntime(contract: JsonObject) {
        val intervalS = (contract["heartbeat"] as? JsonObject)
            ?.get("interval_s")?.toString()?.trim('"')?.toDoubleOrNull()
        if (intervalS != null && intervalS > 0) {
            activeHeartbeatMs = (intervalS * 1000).toLong().coerceIn(100L, 300_000L)
        }
        val reconnect = contract["reconnect"] as? JsonObject
        val baseS = reconnect?.get("backoff_base_s")?.toString()?.trim('"')?.toDoubleOrNull()
        val capS = reconnect?.get("backoff_cap_s")?.toString()?.trim('"')?.toDoubleOrNull()
        if (baseS != null && baseS > 0) {
            activeBackoffBaseMs = (baseS * 1000).toLong().coerceIn(100L, 60_000L)
        }
        if (capS != null && capS > 0) {
            activeBackoffCapMs = (capS * 1000).toLong().coerceAtLeast(activeBackoffBaseMs)
        }
    }

    private inner class Listener : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            reconnectCount = 0
            refreshAlreadyTried = false
            stateFlow.value = State.AUTHED
            // U9：relay 模式连接后首条消息必须是 auth 帧——先于 sync_resume/心跳发出
            val authFrame = pendingRelayAuthFrame
            pendingRelayAuthFrame = null
            if (authFrame != null && sendFrame(authFrame)) {
                sentRelayAuthThisConnection = true
            }
            startHeartbeat()
            // D3 断线补拉：游标 > 0（断线前收过账本帧）时发 sync_resume，
            // 服务端补发 (cursor, head] 的帧（带 replay 标记）；首连游标 0 不发
            resumeMissedFrames()
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            val frame = runCatching { json.parseToJsonElement(text) as? JsonObject }.getOrNull() ?: return
            // D3 游标推进：服务端出站帧带单调 seq（先落账再发送），幂等取大
            frame["seq"]?.toString()?.trim('"')?.toLongOrNull()?.let { seq ->
                if (seq > lastServerSeq) lastServerSeq = seq
            }
            when (frame["type"]?.toString()?.trim('"')) {
                // D3 快照降级：游标过旧/非法/重放预算耗尽——服务端拒绝部分重放。
                // 弃游标并主动拆线走重连档：重连后游标为 0，按首连语义由既有
                // 历史加载链路恢复，不携旧游标补拉（避免漏帧的部分重放）。
                "sync_snapshot_required" -> {
                    lastServerSeq = 0
                    socket?.close(1000, "snapshot-resync")
                    socket = null
                }
                // 后端 pong 是 JSON 帧 {"type":"pong",...}（mobile_pairing.py 消息循环），
                // 裸文本 "pong" 不在契约内；收到即清除等待标记，心跳循环据此判活。
                // D-5：pong 携带 connection_runtime 契约（G4 单源），到达即覆盖
                // 心跳/退避取值；无该字段的 pong（旧后端）保持现行为。
                "pong" -> {
                    awaitingPong.set(false)
                    (frame["connection_runtime"] as? JsonObject)?.let { applyConnectionRuntime(it) }
                }
                "chat:chunk" -> eventsFlow.tryEmit(
                    Event.Chunk(
                        content = frame["content"]?.toString()?.trim('"').orEmpty(),
                        sessionId = frame["session_id"]?.toString()?.trim('"').orEmpty(),
                    ),
                )
                "chat:done" -> eventsFlow.tryEmit(
                    Event.Done(
                        sessionId = frame["session_id"]?.toString()?.trim('"').orEmpty(),
                        messageId = frame["message_id"]?.toString()?.trim('"'),
                    ),
                )
                "chat:cancelled" -> eventsFlow.tryEmit(
                    Event.Cancelled(frame["session_id"]?.toString()?.trim('"').orEmpty()),
                )
                "chat:error", "error" -> {
                    val errorCode = frame["code"]?.toString()?.trim('"').orEmpty()
                    val errorMessage = frame["message"]?.toString()?.trim('"').orEmpty()
                    // U9 relay auth 首帧的已知良性回声：mobile WS 消息循环尚未消费
                    // auth 帧时按 unknown_type 退回（{"...Unknown message type: auth"}）。
                    // auth 帧本身已按新形态发出，这不是链路故障；上抛成对话错误会让
                    // 每次 relay 连接都误报。只压这一种回声，其余错误照常上抛。
                    if (sentRelayAuthThisConnection && errorCode == "unknown_type" &&
                        errorMessage.contains("auth")
                    ) {
                        return
                    }
                    eventsFlow.tryEmit(Event.Error(code = errorCode, message = errorMessage))
                }
                "agent:switched" -> eventsFlow.tryEmit(
                    Event.AgentSwitched(frame["agent_id"]?.toString()?.trim('"').orEmpty()),
                )
                "chat:queued" -> eventsFlow.tryEmit(
                    Event.Queued(
                        sessionId = frame["session_id"]?.toString()?.trim('"').orEmpty(),
                        position = frame["position"]?.toString()?.trim('"')?.toIntOrNull(),
                        attempt = frame["attempt"]?.toString()?.trim('"')?.toIntOrNull(),
                        waitSeconds = frame["wait_seconds"]?.toString()?.trim('"')?.toDoubleOrNull(),
                        reason = frame["reason"]?.toString()?.trim('"'),
                        parked = frame["parked"]?.toString()?.trim('"') == "true",
                    ),
                )
                "chat:reasoning" -> eventsFlow.tryEmit(
                    Event.Reasoning(
                        sessionId = frame["session_id"]?.toString()?.trim('"').orEmpty(),
                        content = frame["content"]?.toString()?.trim('"').orEmpty(),
                    ),
                )
                // 工具事件呈现（卡 C）：computer_action 实时动作流 + 两类交互卡
                "computer_action" -> {
                    val sessionId = frame["session_id"]?.toString()?.trim('"').orEmpty()
                    val payload = ToolActionEvents.payloadOf(frame)
                    if (payload != null) {
                        eventsFlow.tryEmit(
                            Event.ComputerAction(
                                sessionId = sessionId,
                                tool = payload["tool"]?.toString()?.trim('"').orEmpty(),
                                summary = payload["summary"]?.toString()?.trim('"'),
                                success = payload["success"]?.toString()?.trim('"')?.toBooleanStrictOrNull(),
                                payload = payload,
                            ),
                        )
                        ToolActionEvents.parseHostConfirmation(sessionId, payload)?.let {
                            eventsFlow.tryEmit(Event.HostConfirmationRequired(sessionId, it))
                        }
                        ToolActionEvents.parseApproval(sessionId, payload)?.let {
                            eventsFlow.tryEmit(Event.ApprovalRequired(sessionId, it))
                        }
                    }
                }
                // U6 审批：console._extract_approval_payload 同源的移动派生帧
                "chat:approval_required" -> {
                    val sessionId = frame["session_id"]?.toString()?.trim('"').orEmpty()
                    (frame["data"] as? JsonObject)?.let { data ->
                        ToolActionEvents.parseApproval(sessionId, data)?.let {
                            eventsFlow.tryEmit(Event.ApprovalRequired(sessionId, it))
                        }
                    }
                }
                // U1 主机确认：现行移动通路经 tool_result 内容 JSON 透传
                "chat:tool_result" -> {
                    val sessionId = frame["session_id"]?.toString()?.trim('"').orEmpty()
                    (frame["data"] as? JsonObject)?.let { data ->
                        ToolActionEvents.parseHostConfirmationFromToolResult(sessionId, data)?.let {
                            eventsFlow.tryEmit(Event.HostConfirmationRequired(sessionId, it))
                        }
                    }
                }
                // 设备桥命令（2026-11-23 计划卡 A2）：解析成 DeviceCommand 交服务层派发，
                // 通道自身不执行、不回执（回执由 DeviceBridgeService 经 sendDeviceFrame 走同一 socket）
                "device:execute" -> {
                    DeviceBridgeEvents.parseExecute(frame)?.let { command ->
                        eventsFlow.tryEmit(Event.DeviceCommandArrived(command, frame))
                    }
                }
            }
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            // 服务端先发 close（如快照降级链路）：必须应答完成关闭握手，
            // onClosed → 重连链路才得以继续（OkHttp 不会代答 close 帧）
            webSocket.close(code, reason)
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            heartbeatJob?.cancel()
            scheduleReconnect(code, reason)
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            heartbeatJob?.cancel()
            // 握手被 HTTP 401/403 拒绝 = ticket 无效/已消费（一次性票重连必遇），
            // 按 4001 语义走续签重试；其余传输层失败无 close 码：以 1006 语义进入决策
            val handshakeCode = MobileWsClosePolicy.closeCodeForHandshakeRejection(response?.code)
            if (handshakeCode != null) {
                scheduleReconnect(handshakeCode, "handshake rejected: HTTP ${response?.code}")
            } else {
                scheduleReconnect(1006, t.message ?: "transport failure")
            }
        }
    }

    companion object {
        /** 握手唯一装配点：Authorization: Bearer 头携带一次性 ticket（勿用子协议，已证伪） */
        fun buildHandshakeRequest(url: String, ticket: String): Request =
            Request.Builder()
                .url(url)
                .header("Authorization", "Bearer $ticket")
                .build()

        /**
         * 中继入口前缀（后端 protocol.RELAY_ROUTE_PREFIX 同一口径）：
         * relay 模式回连地址形如 `wss://<relay>/t/<routeId>/api/v1/mobile/ws`。
         */
        internal const val RELAY_ROUTE_PREFIX = "/t/"

        /** relay 模式判定：路径段含 /t/<routeId>（直连地址不含，不受影响） */
        internal fun isRelayEntryUrl(url: String): Boolean {
            val afterScheme = url.substringAfter("://", url)
            val pathStart = afterScheme.indexOf('/')
            val path = if (pathStart >= 0) afterScheme.substring(pathStart) else ""
            return path.contains(RELAY_ROUTE_PREFIX)
        }

        /**
         * U9 首条 auth 帧构造：仅 relay 模式且持有裸密钥时成帧；
         * `{"type":"auth","token":"nv1:agent:{stamp}:{nonce}:{hmac}","tokenType":"agent"}`。
         * 裸密钥本地签 nv1 信封（正解），已是信封则原样用；直连模式返回 null（不发）。
         */
        internal fun buildRelayAuthFrame(url: String, secretProvider: () -> String?): JsonObject? {
            if (!isRelayEntryUrl(url)) return null
            val secret = secretProvider()?.trim().orEmpty()
            if (secret.isEmpty()) return null
            val token = if (TunnelTokenSigner.isEnveloped(secret)) secret
            else TunnelTokenSigner.signTunnelToken(secret, TunnelTokenSigner.TYPE_AGENT)
            return JsonObject(
                mapOf(
                    "type" to JsonPrimitive("auth"),
                    "token" to JsonPrimitive(token),
                    "tokenType" to JsonPrimitive(TunnelTokenSigner.TYPE_AGENT),
                ),
            )
        }

        private const val HEARTBEAT_MS = 30_000L
        private const val PONG_TIMEOUT_MS = 10_000L
        private const val DEFAULT_BACKOFF_BASE_MS = 1_000L
        private const val DEFAULT_BACKOFF_CAP_MS = 16_000L

        /**
         * 重连退避（可测纯函数）：min(base * 2^count, cap)，与服务端
         * connection_runtime.reconnect 契约同式；位移上限放宽到 6（64 倍），
         * 既有缺省（1s/16s）行为不变（count≥4 时 cap 先生效）。
         */
        internal fun backoffDelayMs(count: Int, baseMs: Long, capMs: Long): Long =
            (baseMs shl count.coerceAtMost(6)).coerceAtMost(capMs)
    }
}
