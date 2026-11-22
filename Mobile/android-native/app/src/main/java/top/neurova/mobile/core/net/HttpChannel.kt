package top.neurova.mobile.core.net

import java.util.UUID
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import top.neurova.mobile.core.model.ServerProfile
import top.neurova.mobile.core.store.CredentialStore
import top.neurova.mobile.core.store.SingleFlightRefresher

/**
 * HTTP 通道（对齐 Mobile/android/src/utils/http.ts 语义）：
 * - 每请求注入 Bearer + X-Request-ID；
 * - 401 且非鉴权端点 → 单飞续签（POST /auth/refresh）后重放一次；
 * - 响应按信封解包：{data: X} 或裸 X（后端两种形态并存，Vue apiGet/apiPost 同口径）。
 */
class HttpChannel(
    private val profileProvider: () -> ServerProfile,
    private val credentials: CredentialStore,
    private val scope: CoroutineScope,
    client: OkHttpClient = OkHttpClient(),
) {
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }
    private val refresher = SingleFlightRefresher(scope)
    private val refreshMutex = Mutex()
    private val client = client.newBuilder()
        .connectTimeout(15, java.util.concurrent.TimeUnit.SECONDS)
        .readTimeout(30, java.util.concurrent.TimeUnit.SECONDS)
        .build()

    /** 401 后单飞续签（唯一的 token 写回点） */
    var onAuthFailure: (() -> Unit)? = null

    suspend fun getJson(path: String, query: Map<String, String> = emptyMap()): JsonElement =
        execute(buildRequest(path, query, method = "GET", body = null))

    suspend fun postJson(path: String, bodyJson: JsonObject = JsonObject(emptyMap())): JsonElement =
        execute(buildRequest(path, emptyMap(), method = "POST", body = bodyJson))

    suspend fun putJson(path: String, bodyJson: JsonObject = JsonObject(emptyMap())): JsonElement =
        execute(buildRequest(path, emptyMap(), method = "PUT", body = bodyJson))

    suspend fun deleteJson(path: String): JsonElement =
        execute(buildRequest(path, emptyMap(), method = "DELETE", body = null))

    /** 二进制 GET（AIGC 产物预览等）：同一条 Bearer + 401 续签链路，非 2xx 诚实抛 ChannelHttpException */
    suspend fun getBytes(path: String): ByteArray = withContext(Dispatchers.IO) {
        val request = buildRequest(path, emptyMap(), method = "GET", body = null)
        sendWithAuthRetry(request).use { response ->
            if (!response.isSuccessful) {
                throw ChannelHttpException(response.code, request.url.encodedPath, response.body?.string().orEmpty())
            }
            response.body?.bytes() ?: ByteArray(0)
        }
    }

    /** 信封解包：优先取 data 字段，裸形态原样返回 */
    fun unwrapData(element: JsonElement): JsonElement = when {
        element is JsonObject && element.containsKey("data") && element["data"] is JsonObject -> element["data"]!!
        element is JsonObject && element.containsKey("data") && element["data"] is JsonPrimitive -> element["data"]!!
        element is JsonObject && element.containsKey("data") && element["data"] is kotlinx.serialization.json.JsonArray -> element["data"]!!
        else -> element
    }

    private suspend fun execute(request: Request): JsonElement = withContext(Dispatchers.IO) {
        finish(sendWithAuthRetry(request), request)
    }

    /**
     * SSE 事件流开口：返回未消费的 Response（调用方在 IO 线程读流）；
     * 401 走同一条单飞续签 + 重放一次链路，之后由调用方按错误码诚实呈现。
     * OkHttp 同步调用为阻塞 IO，统一收口 Dispatchers.IO（主线程调用即
     * NetworkOnMainThreadException，实测复现过，勿移除）。
     */
    suspend fun streamPost(path: String, bodyJson: JsonObject): okhttp3.Response = withContext(Dispatchers.IO) {
        val request = buildRequest(path, emptyMap(), "POST", bodyJson)
            .newBuilder()
            .header("Accept", "text/event-stream")
            .build()
        sendWithAuthRetry(request)
    }

    private suspend fun sendWithAuthRetry(request: Request): okhttp3.Response {
        val first = client.newCall(request).execute()
        if (first.code != 401 || isAuthPath(request.url.encodedPath)) {
            return first
        }
        first.close()
        // 单飞续签后重放一次（对齐 axios 拦截器 __retried 语义）
        refreshMutex.withLock {
            refresher.run { refreshAccessToken() }
        }
        val replay = client.newCall(withAccessToken(request)).execute()
        if (replay.code == 401) {
            replay.close()
            credentials.clearAuth()
            onAuthFailure?.invoke()
            throw ChannelAuthRevoked(request.url.encodedPath)
        }
        return replay
    }

    private suspend fun refreshAccessToken(): String = withContext(Dispatchers.IO) {
        val refresh = credentials.refreshToken()
        if (refresh.isEmpty()) throw ChannelAuthRevoked("no refresh token")
        val profile = profileProvider()
        val body = json.encodeToString(JsonObject.serializer(), JsonObject(mapOf("refresh_token" to JsonPrimitive(refresh))))
            .toRequestBody("application/json".toMediaType())
        val request = Request.Builder()
            .url(profile.apiBase + "/auth/refresh")
            .post(body)
            .build()
        val response = client.newCall(request).execute()
        response.use {
            if (!it.isSuccessful) throw ChannelAuthRevoked("refresh failed: ${it.code}")
            val payload = json.parseToJsonElement(it.body!!.string())
            val access = (payload as? JsonObject)?.get("access_token")?.toString()?.trim('"').orEmpty()
            val newRefresh = (payload as? JsonObject)?.get("refresh_token")?.toString()?.trim('"')
            if (access.isEmpty()) throw ChannelAuthRevoked("refresh response missing access_token")
            credentials.saveTokens(access, newRefresh ?: refresh)
            access
        }
    }

    private fun buildRequest(path: String, query: Map<String, String>, method: String, body: JsonObject?): Request {
        val profile = profileProvider()
        val url = StringBuilder(profile.apiBase + path)
        if (query.isNotEmpty()) {
            url.append('?').append(query.entries.joinToString("&") { "${it.key}=${java.net.URLEncoder.encode(it.value, "UTF-8")}" })
        }
        val media = "application/json".toMediaType()
        val requestBody = when {
            body != null -> json.encodeToString(JsonObject.serializer(), body).toRequestBody(media)
            method == "POST" -> "{}".toRequestBody(media)
            else -> null
        }
        val builder = Request.Builder().url(url.toString())
        when (method) {
            "GET" -> builder.get()
            "POST" -> builder.post(requestBody!!)
            "DELETE" -> builder.delete(requestBody ?: "{}".toRequestBody(media))
            "PUT" -> builder.put(requestBody!!)
        }
        val token = credentials.accessToken()
        if (token.isNotEmpty()) builder.header("Authorization", "Bearer $token")
        builder.header("X-Request-ID", UUID.randomUUID().toString())
        return builder.build()
    }

    private fun withAccessToken(request: Request): Request {
        val token = credentials.accessToken()
        return request.newBuilder()
            .apply { if (token.isNotEmpty()) header("Authorization", "Bearer $token") }
            .build()
    }

    private fun isAuthPath(path: String): Boolean =
        listOf("/auth/login", "/auth/refresh", "/auth/register").any { path.contains(it) }

    private fun finish(response: okhttp3.Response, request: Request): JsonElement {
        response.use {
            if (!it.isSuccessful) throw ChannelHttpException(it.code, request.url.encodedPath, it.body?.string().orEmpty())
            val text = it.body?.string().orEmpty()
            if (text.isBlank()) return JsonObject(emptyMap())
            return json.parseToJsonElement(text)
        }
    }
}

class ChannelHttpException(val code: Int, val path: String, body: String) : RuntimeException("HTTP $code on $path") {
    val detail: String = run {
        val marker = "\"detail\":\""
        val start = body.indexOf(marker)
        if (start >= 0) body.substring(start + marker.length, body.indexOf('"', start + marker.length)) else body.take(120)
    }
}

class ChannelAuthRevoked(val path: String) : RuntimeException("auth revoked: $path")
