package top.neurova.mobile.core.net

import java.util.UUID
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
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
import top.neurova.mobile.core.store.canonicalOrigin

/** 请求创建时的服务器身份；后续切档、重放、续签都不得改用当前激活档案。 */
internal data class AuthBinding(val serverId: String, val origin: String, val refreshUrl: String)

/**
 * HTTP 通道：
 * - 每请求仅向创建请求时的规范化 origin 注入该 serverId 的 Bearer + X-Request-ID；
 * - 401 且非鉴权端点 → 按 serverId + origin 单飞续签后重放一次；
 * - 响应按信封解包：{data: X} 或裸 X。
 */
class HttpChannel(
    private val profileProvider: () -> ServerProfile,
    private val credentials: CredentialStore,
    private val scope: CoroutineScope,
    client: OkHttpClient = OkHttpClient(),
) {
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }
    private val refresher = SingleFlightRefresher(scope)
    private val client = client.newBuilder()
        .connectTimeout(15, java.util.concurrent.TimeUnit.SECONDS)
        .readTimeout(30, java.util.concurrent.TimeUnit.SECONDS)
        // 重定向会更换 origin，旧 bearer（以及 307/308 的请求体）不得被转发。
        .followRedirects(false)
        .followSslRedirects(false)
        .addInterceptor { chain -> chain.proceed(withBoundAccessToken(chain.request())) }
        .addNetworkInterceptor { chain -> chain.proceed(withBoundAccessToken(chain.request())) }
        .build()

    /** 401 后认证失效回调；清仓只针对请求所属 serverId。 */
    var onAuthFailure: (() -> Unit)? = null

    suspend fun getJson(path: String, query: Map<String, String> = emptyMap()): JsonElement =
        execute(buildRequest(path, query, method = "GET", body = null))

    suspend fun postJson(path: String, bodyJson: JsonObject = JsonObject(emptyMap())): JsonElement =
        execute(buildRequest(path, emptyMap(), method = "POST", body = bodyJson))

    suspend fun putJson(path: String, bodyJson: JsonObject = JsonObject(emptyMap())): JsonElement =
        execute(buildRequest(path, emptyMap(), method = "PUT", body = bodyJson))

    suspend fun deleteJson(path: String): JsonElement =
        execute(buildRequest(path, emptyMap(), method = "DELETE", body = null))

    /** 二进制 GET：同一条 Bearer + 401 续签链路，非 2xx 诚实抛 ChannelHttpException。 */
    suspend fun getBytes(path: String): ByteArray = withContext(Dispatchers.IO) {
        val request = buildRequest(path, emptyMap(), method = "GET", body = null)
        sendWithAuthRetry(request).use { response ->
            if (!response.isSuccessful) {
                throw ChannelHttpException(response.code, request.url.encodedPath, response.body?.string().orEmpty())
            }
            response.body?.bytes() ?: ByteArray(0)
        }
    }

    /** 信封解包：优先取 data 字段，裸形态原样返回。 */
    fun unwrapData(element: JsonElement): JsonElement = when {
        element is JsonObject && element.containsKey("data") && element["data"] is JsonObject -> element["data"]!!
        element is JsonObject && element.containsKey("data") && element["data"] is JsonPrimitive -> element["data"]!!
        element is JsonObject && element.containsKey("data") && element["data"] is kotlinx.serialization.json.JsonArray -> element["data"]!!
        else -> element
    }

    private suspend fun execute(request: Request): JsonElement = withContext(Dispatchers.IO) {
        finish(sendWithAuthRetry(request), request)
    }

    /** SSE 开口：401 走同一条单飞续签 + 重放一次链路。 */
    suspend fun streamPost(path: String, bodyJson: JsonObject): okhttp3.Response = withContext(Dispatchers.IO) {
        val request = buildRequest(path, emptyMap(), "POST", bodyJson)
            .newBuilder()
            .header("Accept", "text/event-stream")
            .build()
        sendWithAuthRetry(request)
    }

    private suspend fun sendWithAuthRetry(request: Request): okhttp3.Response {
        val binding = checkNotNull(request.tag(AuthBinding::class.java)) { "请求缺少服务器凭据绑定" }
        val first = client.newCall(request).execute()
        if (first.code != 401 || isAuthPath(request.url.encodedPath)) {
            return first
        }
        first.close()
        refresher.run("${binding.serverId}\u0000${binding.origin}") { refreshAccessToken(binding) }
        val replay = client.newCall(withAccessToken(request)).execute()
        if (replay.code == 401) {
            replay.close()
            credentials.clearAuth(binding.serverId)
            onAuthFailure?.invoke()
            throw ChannelAuthRevoked(request.url.encodedPath)
        }
        return replay
    }

    private suspend fun refreshAccessToken(binding: AuthBinding): String = withContext(Dispatchers.IO) {
        val refresh = credentials.refreshToken(binding.serverId, binding.origin)
        if (refresh.isEmpty()) throw ChannelAuthRevoked("no refresh token")
        val body = json.encodeToString(JsonObject.serializer(), JsonObject(mapOf("refresh_token" to JsonPrimitive(refresh))))
            .toRequestBody("application/json".toMediaType())
        // refreshUrl 来自原请求档案，不重新读取可能已被切换的 profileProvider。
        val request = Request.Builder().url(binding.refreshUrl).post(body).build()
        val response = client.newCall(request).execute()
        response.use {
            if (!it.isSuccessful) throw ChannelAuthRevoked("refresh failed: ${it.code}")
            val payload = json.parseToJsonElement(it.body!!.string())
            val access = (payload as? JsonObject)?.get("access_token")?.toString()?.trim('"').orEmpty()
            val newRefresh = (payload as? JsonObject)?.get("refresh_token")?.toString()?.trim('"')
            if (access.isEmpty()) throw ChannelAuthRevoked("refresh response missing access_token")
            credentials.saveTokens(binding.serverId, binding.origin, access, newRefresh ?: refresh)
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
        val origin = checkNotNull(canonicalOrigin(builder.build().url.toString()))
        builder.tag(AuthBinding::class.java, AuthBinding(profile.id, origin, profile.apiBase + "/auth/refresh"))
        builder.header("X-Request-ID", UUID.randomUUID().toString())
        return withBoundAccessToken(builder.build())
    }

    private fun withAccessToken(request: Request): Request = withBoundAccessToken(request)

    /** 应用与网络两道拦截都在真实发送前复核；origin 变化或无绑定时一律摘除 Authorization。 */
    private fun withBoundAccessToken(request: Request): Request {
        val binding = request.tag(AuthBinding::class.java)
        val token = binding?.takeIf { canonicalOrigin(request.url.toString()) == it.origin }
            ?.let { credentials.accessToken(it.serverId, it.origin) }.orEmpty()
        return request.newBuilder().apply {
            if (token.isEmpty()) removeHeader("Authorization") else header("Authorization", "Bearer $token")
        }.build()
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
