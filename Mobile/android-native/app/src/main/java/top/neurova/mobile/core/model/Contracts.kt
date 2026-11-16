package top.neurova.mobile.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * 服务器档案：一台可连接的 Neurova 服务端（手机客户端设计方案 §4.5）。
 * 与 Mobile/android/src/types.ts 的 ServerProfile 同源同字段。
 */
@Serializable
data class ServerProfile(
    val id: String,
    val name: String,
    /** 直连：http(s)://host:port；中继：https://<relay>/t/<routeId> */
    val baseUrl: String,
    /** direct=内网直连；relay=自研中继反向隧道 */
    val entryMode: EntryMode = EntryMode.DIRECT,
    /** 最近成功登录的账号（仅展示，切换档案不串账号） */
    val lastAccount: String? = null,
    val lastConnectedAt: Long? = null,
) {
    /** API 根：唯一拼装点（Vue 端 servers.apiBase 同语义） */
    val apiBase: String get() = baseUrl.trimEnd('/') + "/api/v1"

    enum class EntryMode { DIRECT, RELAY }
}

/** 登录令牌对（access 60 分钟 / refresh 7 天，JWT HS256，见设计方案 §2.3） */
@Serializable
data class TokenPair(
    val accessToken: String,
    val refreshToken: String,
)

/** 当前用户（/auth/me 返回；role 决定管理员域入口渲染） */
@Serializable
data class CurrentUser(
    val id: String,
    val username: String,
    val email: String? = null,
    val role: String = "",
    val tenantId: String? = null,
    val tenantName: String? = null,
)

/** Agent 条目（GET /agents 裸数组的 AgentInfo 投影，agent.py 事实源；测试咬合实测载荷） */
@Serializable
data class AgentItem(
    @SerialName("agent_id") val agentId: String,
    val name: String = "",
    val description: String? = null,
    val status: String? = null,
    val model: String? = null,
    val provider: String? = null,
    @SerialName("memory_enabled") val memoryEnabled: Boolean = false,
    @SerialName("tools_count") val toolsCount: Int = 0,
)

/**
 * 会话摘要（GET /console/chat/sessions，console.py 摘要形状原样；鸿蒙 SessionsApi 同源）。
 * 字段是 `id`/`pinned`——不是臆写的 session_id/is_pinned（真实载荷解码已钉进 SessionWireTest）。
 */
@Serializable
data class ChatSessionItem(
    val id: String,
    val title: String = "新对话",
    @SerialName("agent_id") val agentId: String = "",
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
    val pinned: Boolean = false,
    @SerialName("sort_order") val sortOrder: Int = 0,
    @SerialName("source_channel") val sourceChannel: String? = null,
    @SerialName("channel_name") val channelName: String? = null,
)

/** 会话历史单条（GET /console/chat/history 的 messages 元素：session_manager 存储形状 {role, content}） */
@Serializable
data class ChatHistoryEntry(
    val role: String,
    val content: String,
)

/** 单条聊天消息（本地渲染态；会话历史从 /chat/history 回放） */
@Serializable
data class ChatMessage(
    val id: String,
    /** user / assistant */
    val role: String,
    val content: String,
    val reasoning: String? = null,
    /** streaming / done / error / cancelled */
    val status: String = "done",
)

/** 配对三端点响应（POST /mobile/pairing/resolve | confirm | refresh，§5.3/§8.2） */
@Serializable
data class PairingResolved(
    @SerialName("ws_url") val wsUrl: String,
    @SerialName("pairing_id") val pairingId: String,
    @SerialName("expires_in") val expiresIn: Int,
    val status: String = "",
)

@Serializable
data class PairingConfirmed(
    @SerialName("ws_token") val wsToken: String,
    @SerialName("ws_url") val wsUrl: String,
    @SerialName("expires_in") val expiresIn: Int,
    @SerialName("device_secret") val deviceSecret: String? = null,
    @SerialName("pairing_id") val pairingId: String? = null,
)

@Serializable
data class PairingRefreshed(
    @SerialName("connect_ticket") val connectTicket: String,
    @SerialName("pairing_id") val pairingId: String,
    @SerialName("expires_in") val expiresIn: Int,
)
