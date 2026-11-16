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
import top.neurova.mobile.core.protocol.MobileWsClosePolicy

/**
 * 移动 WS 通道（手机客户端设计方案 §5.3；对齐鸿蒙 WebSocketAdapter 语义）：
 * - 握手：一次性 connect_ticket 走 **Authorization: Bearer** 头（后端 _ticketFromHandshake
 *   的优先通道，鸿蒙同款）。子协议 `neurova.auth.<ticket>` 形态已证伪——ticket 含冒号，
 *   不是合法 RFC6455 子协议 token，握手必败（2026-11-16 wsprobe 实测），勿回潮；
 * - 心跳：30s 应用层 ping/pong，帧契约 `{"type":"ping"}` / `{"type":"pong"}`（与后端
 *   mobile_pairing.py 消息循环、鸿蒙 WebSocketAdapter 三方同源）；pong 超时 10s 视为断流
 *   （中继上静默断流没有 close 帧）；
 * - 关闭分档：由 MobileWsClosePolicy 裁决——4001 先续签重试一次（唯一需重新配对的是
 *   续签被拒 device_deregistered）；4008 不重连；manual 恒终态。
 */
class MobileWsChannel(
    private val scope: CoroutineScope,
    private val wsUrlProvider: () -> String?,
    private val ticketProvider: () -> String?,
    /** 4001 续签：成功返回新 ticket，失败抛出（= 设备已解除，终态） */
    private val refreshTicket: suspend () -> String,
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

    /** 本周期是否仍在等 pong（OkHttp 读线程置 false，心跳协程读；判定超时的唯一依据） */
    private val awaitingPong = AtomicBoolean(false)
    private var reconnectCount = 0
    private var refreshAlreadyTried = false
    private var manualClosed = false

    fun connect() {
        // 手动关闭是终态（MobileWsClosePolicy：manual 恒终态）——挂起的重连协程
        // 不得借 connect() 复活已关闭的通道
        if (manualClosed) return
        manualClosed = false
        val url = wsUrlProvider() ?: run { stateFlow.value = State.FAILED; return }
        val ticket = ticketProvider() ?: run { stateFlow.value = State.FAILED; return }
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

    fun close() {
        manualClosed = true
        heartbeatJob?.cancel()
        socket?.close(1000, "manual")
        socket = null
        stateFlow.value = State.CLOSED
    }

    private fun sendFrame(frame: JsonObject): Boolean = socket?.send(json.encodeToString(JsonObject.serializer(), frame)) ?: false

    private fun buildJsonObject(vararg pairs: Pair<String, String?>): JsonObject = JsonObject(
        pairs.mapNotNull { (key, value) -> value?.let { key to JsonPrimitive(it) } }.toMap(),
    )

    private fun startHeartbeat() {
        heartbeatJob?.cancel()
        heartbeatJob = scope.launch {
            while (true) {
                delay(heartbeatIntervalMs)
                awaitingPong.set(true)
                // 心跳是 JSON 帧 {"type":"ping"}：后端消息循环 json.loads 只吃 JSON，
                // 裸文本 "ping" 会炸掉连接（鸿蒙 WebSocketAdapter 同契约，勿回潮）
                if (!sendFrame(buildJsonObject("type" to "ping"))) break
                delay(pongTimeoutMs)
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

    private fun backoffMs(count: Int): Long = (1000L shl count.coerceAtMost(4)).coerceAtMost(16000)

    private inner class Listener : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            reconnectCount = 0
            refreshAlreadyTried = false
            stateFlow.value = State.AUTHED
            startHeartbeat()
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            val frame = runCatching { json.parseToJsonElement(text) as? JsonObject }.getOrNull() ?: return
            when (frame["type"]?.toString()?.trim('"')) {
                // 后端 pong 是 JSON 帧 {"type":"pong",...}（mobile_pairing.py 消息循环），
                // 裸文本 "pong" 不在契约内；收到即清除等待标记，心跳循环据此判活
                "pong" -> awaitingPong.set(false)
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
                "chat:error", "error" -> eventsFlow.tryEmit(
                    Event.Error(
                        code = frame["code"]?.toString()?.trim('"').orEmpty(),
                        message = frame["message"]?.toString()?.trim('"').orEmpty(),
                    ),
                )
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
            }
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

        private const val HEARTBEAT_MS = 30_000L
        private const val PONG_TIMEOUT_MS = 10_000L
    }
}
