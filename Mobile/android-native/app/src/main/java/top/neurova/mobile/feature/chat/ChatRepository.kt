package top.neurova.mobile.feature.chat

import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import top.neurova.mobile.core.model.ChatHistoryEntry
import top.neurova.mobile.core.model.ChatMessage
import top.neurova.mobile.core.model.ChatSessionItem
import top.neurova.mobile.core.net.HttpChannel

/**
 * 会话域仓库（F4 会话列表 / F5 历史 / F6 抽屉操作集的唯一数据源）。
 * 端点与 PC 端 ChatSessionSidebar 同源（console.py）：
 *   GET  /console/chat/sessions[?agent_id=]   摘要列表
 *   GET  /console/chat/sessions/archived      归档列表
 *   GET  /console/chat/history?session_id=    消息回放 {role,content}
 *   POST /console/chat/new                    建会话 → session_id
 *   PUT  /console/chat/sessions/{id}          重命名 {title}
 *   POST /console/chat/sessions/{id}/pin      置顶 {pinned}
 *   POST /console/chat/sessions/{id}/archive | /unarchive | /fork
 *   DELETE /console/chat/sessions/{id}
 */
class ChatRepository(private val http: HttpChannel) {

    private val json = Json { ignoreUnknownKeys = true }

    suspend fun listSessions(agentId: String? = null): List<ChatSessionItem> =
        listBy(agentId, archived = false)

    suspend fun listArchived(agentId: String? = null): List<ChatSessionItem> =
        listBy(agentId, archived = true)

    private suspend fun listBy(agentId: String?, archived: Boolean): List<ChatSessionItem> {
        val path = if (archived) "/console/chat/sessions/archived" else "/console/chat/sessions"
        val query = if (agentId.isNullOrBlank()) emptyMap() else mapOf("agent_id" to agentId)
        val data = http.unwrapData(http.getJson(path, query))
        val sessions = (data as? JsonObject)?.get("sessions") ?: return emptyList()
        return json.decodeFromJsonElement(ListSerializer(ChatSessionItem.serializer()), sessions)
    }

    /** 历史回放：{role,content} → 本地渲染态（id 用序号，状态恒 done） */
    suspend fun history(sessionId: String): List<ChatMessage> {
        val data = http.unwrapData(http.getJson("/console/chat/history", mapOf("session_id" to sessionId)))
        val messages = (data as? JsonObject)?.get("messages") ?: return emptyList()
        val entries = json.decodeFromJsonElement(ListSerializer(ChatHistoryEntry.serializer()), messages)
        return entries.mapIndexed { index, entry ->
            ChatMessage(id = "h-$sessionId-$index", role = entry.role, content = entry.content)
        }
    }

    /** 建会话：返回 session_id（标题缺省由后端定「新对话」） */
    suspend fun createSession(agentId: String? = null, title: String? = null): String {
        val body = buildMap {
            if (!agentId.isNullOrBlank()) put("agent_id", JsonPrimitive(agentId))
            if (!title.isNullOrBlank()) put("title", JsonPrimitive(title))
        }
        val data = http.unwrapData(http.postJson("/console/chat/new", JsonObject(body)))
        return (data as? JsonObject)?.get("session_id")?.toString()?.trim('"').orEmpty()
    }

    suspend fun rename(sessionId: String, title: String) {
        http.putJson("/console/chat/sessions/$sessionId", JsonObject(mapOf("title" to JsonPrimitive(title))))
    }

    suspend fun setPinned(sessionId: String, pinned: Boolean) {
        http.postJson("/console/chat/sessions/$sessionId/pin", JsonObject(mapOf("pinned" to JsonPrimitive(pinned))))
    }

    suspend fun archive(sessionId: String) {
        http.postJson("/console/chat/sessions/$sessionId/archive")
    }

    suspend fun unarchive(sessionId: String) {
        http.postJson("/console/chat/sessions/$sessionId/unarchive")
    }

    suspend fun fork(sessionId: String) {
        http.postJson("/console/chat/sessions/$sessionId/fork")
    }

    suspend fun remove(sessionId: String) {
        http.deleteJson("/console/chat/sessions/$sessionId")
    }
}
