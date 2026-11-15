package top.neurova.mobile.core.net

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.job
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import top.neurova.mobile.core.model.ServerProfile
import top.neurova.mobile.core.protocol.SseFrameParser

/**
 * 对话 SSE 主通道（POST /chat/stream，§8.3 事件映射）：
 * start/message/reasoning/retry/parked/error/done，": ping" 心跳行由 SseFrameParser 忽略。
 * 取消：协程取消 → 中断 HTTP call → 抛 CancellationException（语义=用户停止生成）。
 */
class ChatSseChannel(
    private val profileProvider: () -> ServerProfile,
    private val http: HttpChannel,
    client: OkHttpClient = OkHttpClient(),
) {
    private val json = Json { ignoreUnknownKeys = true }
    private val client = client.newBuilder()
        .readTimeout(0, java.util.concurrent.TimeUnit.MILLISECONDS) // SSE 长连接不设读超时
        .build()

    sealed interface Event {
        data class Start(val requestId: String, val sessionId: String) : Event
        data class MessageDelta(val content: String) : Event
        data class ReasoningDelta(val content: String) : Event
        data class Retrying(val phase: String, val waitSeconds: Long) : Event
        data class Parked(val runId: String) : Event
        data class Failed(val message: String) : Event
        data class Completed(val requestId: String, val sessionId: String) : Event
    }

    /**
     * 流式对话。挂起至流结束（done/error）或协程取消。
     * @throws ChannelHttpException 非 2xx（含 detail 文案）
     */
    suspend fun stream(
        message: String,
        agentId: String?,
        sessionId: String?,
        onEvent: (Event) -> Unit,
    ): Unit = withContext(Dispatchers.IO) {
        val response = http.streamPost("/chat/stream", requestBodyOf(message, agentId, sessionId))
        response.use { resp ->
            if (!resp.isSuccessful) {
                throw ChannelHttpException(resp.code, "/chat/stream", resp.body?.string().orEmpty())
            }
            val source = resp.body?.charStream() ?: return@use
            val parser = SseFrameParser()
            val buffer = CharArray(4096)
            val reader = source.buffered(8192)
            while (currentCoroutineContext().isActive) {
                val n = reader.read(buffer)
                if (n < 0) break
                parser.feed(String(buffer, 0, n)).forEach { frame -> dispatch(frame, onEvent) }
            }
        }
    }

    private fun requestBodyOf(message: String, agentId: String?, sessionId: String?): JsonObject = JsonObject(
        buildMap {
            put("message", JsonPrimitive(message))
            put("agent_id", JsonPrimitive(agentId ?: "default"))
            sessionId?.let { put("session_id", JsonPrimitive(it)) }
        },
    )

    private fun dispatch(frame: SseFrameParser.SseFrame, onEvent: (Event) -> Unit) {
        val payload = runCatching { json.parseToJsonElement(frame.data) as? JsonObject }.getOrNull() ?: JsonObject(emptyMap())
        fun textOf(key: String) = (payload[key] as? JsonPrimitive)?.content.orEmpty()
        when (frame.event) {
            "start" -> onEvent(Event.Start(textOf("request_id"), textOf("session_id")))
            "message" -> onEvent(Event.MessageDelta(textOf("content")))
            "reasoning" -> onEvent(Event.ReasoningDelta(textOf("content")))
            "retry" -> onEvent(Event.Retrying(textOf("phase"), (payload["wait_seconds"] as? JsonPrimitive)?.content?.toLongOrNull() ?: 0L))
            "parked" -> onEvent(Event.Parked(textOf("run_id")))
            "error" -> onEvent(Event.Failed(textOf("message").ifBlank { textOf("detail") }))
            "done" -> onEvent(Event.Completed(textOf("request_id"), textOf("session_id")))
        }
    }
}
