package top.neurova.mobile.feature.chat

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import top.neurova.mobile.core.net.HttpChannel

/**
 * 确认/审批卡动作仓库（U1 主机确认 / U6 动态干预审批）：
 * - POST /settings/ssh-credentials/host-key/confirm —— 主机公钥确认（U1 卡 A 后端端点，
 *   经 SshHostStore.mark_confirmed 落库后 SSH 首连放行）；
 * - POST /governance/approvals/{id}/approve | /reject —— 动态干预审批链（批准后重放执行）。
 */
class ToolActionRepository(private val http: HttpChannel) {

    /** U1 主机确认：body 含 agent_id/host/port/fingerprint（+key_type），known_hosts 按 agent 分桶 */
    suspend fun confirmSshHostKey(
        agentId: String,
        host: String,
        port: Int,
        fingerprint: String,
        keyType: String?,
    ): JsonElement {
        val fields = linkedMapOf<String, JsonElement>(
            "agent_id" to JsonPrimitive(agentId),
            "host" to JsonPrimitive(host),
            "port" to JsonPrimitive(port),
            "fingerprint" to JsonPrimitive(fingerprint),
        )
        if (!keyType.isNullOrBlank()) fields["key_type"] = JsonPrimitive(keyType)
        return http.unwrapData(
            http.postJson("/settings/ssh-credentials/host-key/confirm", JsonObject(fields)),
        )
    }

    /** U6 批准：批准后服务端按审批单 metadata 重放执行 */
    suspend fun approveApproval(requestId: String, approvedBy: String = "user"): JsonElement =
        http.unwrapData(
            http.postJson(
                "/governance/approvals/$requestId/approve",
                JsonObject(mapOf("approved_by" to JsonPrimitive(approvedBy))),
            ),
        )

    /** U6 拒绝：审批单进 rejected 终态 */
    suspend fun rejectApproval(requestId: String, rejectedBy: String = "user"): JsonElement =
        http.unwrapData(
            http.postJson(
                "/governance/approvals/$requestId/reject",
                JsonObject(mapOf("approved_by" to JsonPrimitive(rejectedBy))),
            ),
        )
}
