package top.neurova.mobile.core.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.intOrNull

/**
 * 工具事件 → 确认/审批卡 view-model（U1 主机确认卡 / U6 动态干预审批卡）。
 *
 * 数据源两路，收口到同一组 view-model：
 * - WS `computer_action` 事件载荷：`needs_host_confirmation{host,port,fingerprint,key_type,agent_id}`
 *   与 `pending_approval{approval_id,tool_name,params,governance}` 随行（tool_executor
 *   `_emit_computer_event` 单源广播）；
 * - 移动 WS 现行派生帧：`chat:approval_required`（console._extract_approval_payload 同源）
 *   与 `chat:tool_result` 内容里的 needs_host_confirmation 结构化结果。
 */
data class HostConfirmationCard(
    val sessionId: String,
    val host: String,
    val port: Int? = null,
    val fingerprint: String = "",
    val keyType: String? = null,
    val agentId: String? = null,
    val message: String? = null,
)

data class ApprovalCard(
    val sessionId: String,
    val approvalId: String,
    val toolName: String = "",
    val params: JsonObject? = null,
    val governance: JsonObject? = null,
    val reason: String? = null,
)

object ToolActionEvents {

    private val lenientJson = Json { ignoreUnknownKeys = true; isLenient = true }

    /**
     * computer_action 帧的载荷取法（容错三形）：`payload` / `data` / 帧本体即载荷。
     * 后端 session_sync 事件与移动派生帧的包裹键名不同，这里不臆造单一形状。
     */
    fun payloadOf(frame: JsonObject): JsonObject? {
        (frame["payload"] as? JsonObject)?.let { return it }
        (frame["data"] as? JsonObject)?.let { return it }
        return if (frame.containsKey("tool") || frame.containsKey("needs_host_confirmation") ||
            frame.containsKey("pending_approval") || frame.containsKey("approval_id")
        ) frame else null
    }

    /** U1 主机确认卡：needs_host_confirmation 为真才成卡 */
    fun parseHostConfirmation(sessionId: String, payload: JsonObject): HostConfirmationCard? {
        if (payload.primitiveBool("needs_host_confirmation") != true) return null
        val host = payload.primitiveString("host")?.trim().orEmpty()
        if (host.isEmpty()) return null
        return HostConfirmationCard(
            sessionId = sessionId,
            host = host,
            port = payload.primitiveInt("port"),
            fingerprint = payload.primitiveString("fingerprint").orEmpty(),
            keyType = payload.primitiveString("key_type"),
            agentId = payload.primitiveString("agent_id"),
            message = payload.primitiveString("error") ?: payload.primitiveString("message"),
        )
    }

    /** chat:tool_result 内容是结果 JSON 字符串：needs_host_confirmation 随内容透传 */
    fun parseHostConfirmationFromToolResult(sessionId: String, data: JsonObject): HostConfirmationCard? {
        val content = data.primitiveString("content") ?: return null
        val parsed = runCatching { lenientJson.parseToJsonElement(content) }.getOrNull() as? JsonObject
            ?: return null
        return parseHostConfirmation(sessionId, parsed)
    }

    /** U6 审批卡：approval_id 是唯一必需要素（pending_approval 帧与 approval_required 帧同收） */
    fun parseApproval(sessionId: String, payload: JsonObject): ApprovalCard? {
        val approvalId = payload.primitiveString("approval_id")?.trim().orEmpty()
        if (approvalId.isEmpty()) return null
        return ApprovalCard(
            sessionId = sessionId,
            approvalId = approvalId,
            toolName = payload.primitiveString("tool_name") ?: payload.primitiveString("tool").orEmpty(),
            params = payload["params"] as? JsonObject,
            governance = payload["governance"] as? JsonObject,
            reason = payload.primitiveString("reason") ?: payload.primitiveString("error"),
        )
    }
}

/** JsonPrimitive 安全取值（JsonNull 不当值用；非 Primitive 一律 null） */
internal fun JsonObject.primitiveString(key: String): String? {
    val primitive = this[key] as? JsonPrimitive ?: return null
    if (primitive is JsonNull) return null
    return primitive.content
}

internal fun JsonObject.primitiveBool(key: String): Boolean? {
    val primitive = this[key] as? JsonPrimitive ?: return null
    if (primitive is JsonNull) return null
    return primitive.booleanOrNull
}

internal fun JsonObject.primitiveInt(key: String): Int? {
    val primitive = this[key] as? JsonPrimitive ?: return null
    if (primitive is JsonNull) return null
    return primitive.intOrNull
}
