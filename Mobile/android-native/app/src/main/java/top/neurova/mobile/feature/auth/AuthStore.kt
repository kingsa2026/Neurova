package top.neurova.mobile.feature.auth

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import top.neurova.mobile.core.model.CurrentUser
import top.neurova.mobile.core.net.ChannelHttpException
import top.neurova.mobile.core.net.HttpChannel
import top.neurova.mobile.core.store.CredentialStore

/**
 * 认证仓（手机客户端设计方案 §5.1；对齐 Mobile/android/src/stores/auth.ts）：
 * 登录 → JWT（access 60m / refresh 7d）→ /auth/me 取用户与租户（部门根）。
 * role=admin 决定「我的」页管理员域入口渲染与路由守卫。
 */
class AuthStore(
    private val http: HttpChannel,
    private val credentials: CredentialStore,
    private val servers: top.neurova.mobile.feature.servers.ServersStore,
) {
    var user by mutableStateOf<CurrentUser?>(null)
        private set
    var loading by mutableStateOf(false)
        private set

    val isAdmin: Boolean get() = user?.role == "admin"

    /** 恢复会话：安全存储里有 access_token 则拉 /auth/me 验活 */
    suspend fun restore(): Boolean {
        if (credentials.accessToken().isEmpty()) return false
        return runCatching { fetchMe() }.isSuccess
    }

    /** @throws LoginRejected 带后端 detail 文案 */
    suspend fun login(username: String, password: String) {
        loading = true
        try {
            val body = JsonObject(
                mapOf(
                    "username" to JsonPrimitive(username),
                    "password" to JsonPrimitive(password),
                ),
            )
            val element = http.unwrapData(http.postJson("/auth/login", body))
            val payload = element as? JsonObject ?: throw LoginRejected("登录响应格式异常")
            val access = (payload["access_token"] as? JsonPrimitive)?.content
                ?: throw LoginRejected(payload.detail() ?: "登录失败")
            val refresh = (payload["refresh_token"] as? JsonPrimitive)?.content.orEmpty()
            credentials.saveTokens(access, refresh)
            fetchMe()
            servers.markConnected(user?.username ?: username)
        } finally {
            loading = false
        }
    }

    suspend fun logout() {
        runCatching { http.postJson("/auth/logout") }
        credentials.clearAuth()
        user = null
    }

    private suspend fun fetchMe() {
        val element = http.unwrapData(http.getJson("/auth/me"))
        val payload = element as? JsonObject ?: throw LoginRejected("用户信息格式异常")
        user = CurrentUser(
            id = payload.stringOf("id") ?: payload.stringOf("sub") ?: "",
            username = payload.stringOf("username").orEmpty(),
            email = payload.stringOf("email"),
            role = payload.stringOf("role") ?: "user",
            tenantId = payload.stringOf("tenant_id") ?: "default",
            tenantName = payload.stringOf("tenant_name") ?: payload.stringOf("tenant_id") ?: "default",
        )
    }
}

private fun JsonObject.stringOf(key: String): String? =
    (this[key] as? JsonPrimitive)?.content?.takeIf { it.isNotBlank() && it != "null" }

private fun JsonObject.detail(): String? = stringOf("detail") ?: stringOf("message")

class LoginRejected(message: String) : RuntimeException(message)
