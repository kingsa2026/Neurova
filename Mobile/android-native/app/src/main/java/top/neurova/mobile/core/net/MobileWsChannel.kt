package top.neurova.mobile.core.net

import java.util.concurrent.TimeUnit
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
 * 移动 WS 通道（手机客户端设计方案 §5.3 / §8.3 备用通道；对齐鸿蒙 WebSocketAdapter 语义）：
 * - 握手：一次性 connect_ticket 走 Sec-WebSocket-Protocol 子协议 `neurova.auth.<ticket>`
 *   （服务端两条通道都支持，token 不进 URL）；
 * - 心跳：30s 应用层 ping/pong，pong 超时 10s 视为断流（中继上静默断流没有 close 帧）；
 * - 关闭分档：由 MobileWsClosePolicy 裁决——4001 先续签重试一次（唯一需重新配对的是
 *   续签被拒 device_deregistered）；4008 不重连；manual 恒终态。
 */
class MobileWsChannel(
    private val scope: CoroutineScope,
    private val wsUrlProvider: () -> String?,
    private val ticketProvider: () -> String?,
    /** 4001 续签：成功返回新 ticket，失败抛出（= 设备已解除，终态） */
    private val refreshTicket: suspend () -> String,
    client: OkHttpClient = OkHttpClient(),
) {
    enum class State { IDLE, CONNECTING, AUTHED, REAUTHING, RECONNECTING, FAILED, CLOSED }

    sealed interface Event {
        data class Chunk(val content: String, val sessionId: String) : Event
        data class Done(val sessionId: String, val messageId: String?) : Event
        data class Cancelled(val sessionId: String) : Event
        data class Error(val code: String, val message: String) : Event
        data class AgentSwitched(val agentId: String) : Event
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
    private var reconnectCount = 0
    private var refreshAlreadyTried = false
    private var manualClosed = false

    fun connect() {
        manualClosed = false
        val url = wsUrlProvider() ?: run { stateFlow.value = State.FAILED; return }
        val ticket = ticketProvider() ?: run { stateFlow.value = State.FAILED; return }
        stateFlow.value = State.CONNECTING
        val request = Request.Builder()
            .url(url)
            .header("Sec-WebSocket-Protocol", "neurova.auth.$ticket")
            .build()
        socket = client.newWebSocket(request, Listener())
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
                delay(HEARTBEAT_MS)
                if (socket?.send("ping") != true) break
                delay(PONG_TIMEOUT_MS)
                // 超时未收到 pong：视为断流（无 close 帧），走传输层重连档
                socket?.close(1006, "pong-timeout")
                socket = null
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
            if (text == "pong") return
            val frame = runCatching { json.parseToJsonElement(text) as? JsonObject }.getOrNull() ?: return
            when (frame["type"]?.toString()?.trim('"')) {
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
            }
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            heartbeatJob?.cancel()
            scheduleReconnect(code, reason)
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            heartbeatJob?.cancel()
            // 传输层失败无 close 码：以 1006 语义进入决策
            scheduleReconnect(1006, t.message ?: "transport failure")
        }
    }

    private companion object {
        const val HEARTBEAT_MS = 30_000L
        const val PONG_TIMEOUT_MS = 10_000L
    }
}
