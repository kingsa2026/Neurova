package top.neurova.mobile.feature.pairing

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import java.util.UUID
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import top.neurova.mobile.core.model.PairingConfirmed
import top.neurova.mobile.core.model.PairingResolved
import top.neurova.mobile.core.net.HttpChannel
import top.neurova.mobile.core.store.CredentialStore

/**
 * 配对凭证仓（手机客户端设计方案 §5.3/§4.7）：
 * 长期设备身份（pairingId + deviceSecret）进 CredentialStore 加密分仓；
 * 一次性 connect_ticket 仅内存；WS 过期用设备身份走 /pairing/refresh 续签（免回屏重扫）。
 */
class PairingStore(
    private val http: HttpChannel,
    private val credentials: CredentialStore,
) {
    private val json = Json { ignoreUnknownKeys = true }
    var paired by mutableStateOf(false)
        private set
    var wsUrl by mutableStateOf("")
        private set
    var ticket by mutableStateOf("")
        private set
    var ticketExpiresAt by mutableStateOf(0L)
        private set
    private var pairingId: String = ""

    /** 启动恢复：本地有长期设备身份即视为已配对（ticket 启动为空，连接前自动续签） */
    fun restore(): Boolean {
        val identity = credentials.pairedIdentity() ?: return false
        pairingId = identity.first
        paired = true
        return true
    }

    fun deviceName(): String = "Android " + android.os.Build.MODEL.orEmpty().ifBlank { "设备" }

    /** 一扫配全：resolve（ref 换回连地址）→ confirm（拿设备身份与一次性票据） */
    suspend fun pairByRef(ref: String) {
        val resolvedElement = http.unwrapData(
            http.postJson("/mobile/pairing/resolve", JsonObject(mapOf("ref" to JsonPrimitive(ref)))),
        )
        val resolved = decode<ResolvedWire>(resolvedElement.toString())
        val confirmElement = http.unwrapData(
            http.postJson(
                "/mobile/pairing/confirm",
                JsonObject(
                    mapOf(
                        "ref" to JsonPrimitive(ref),
                        "deviceName" to JsonPrimitive(deviceName()),
                        "deviceType" to JsonPrimitive("android"),
                    ),
                ),
            ),
        )
        val confirmed = decode<ConfirmedWire>(confirmElement.toString())
        applyConfirmed(resolved, confirmed)
    }

    /** ticket 续签（§5.1b：只换 ticket，不改设备身份） */
    suspend fun refreshTicket(): String {
        val identity = credentials.pairedIdentity() ?: throw IllegalStateException("device_not_paired")
        val element = http.unwrapData(
            http.postJson(
                "/mobile/pairing/refresh",
                JsonObject(
                    mapOf(
                        "pairing_id" to JsonPrimitive(identity.first),
                        "device_secret" to JsonPrimitive(identity.second),
                        "challenge" to JsonPrimitive(UUID.randomUUID().toString()),
                    ),
                ),
            ),
        )
        val refreshed = decode<RefreshedWire>(element.toString())
        ticket = refreshed.connectTicket
        ticketExpiresAt = System.currentTimeMillis() + (refreshed.expiresIn ?: 60) * 1000
        return ticket
    }

    private suspend fun applyConfirmed(resolved: ResolvedWire?, confirmed: ConfirmedWire) {
        pairingId = confirmed.pairingId ?: resolved?.pairingId ?: ""
        val deviceSecret = confirmed.deviceSecret.orEmpty()
        wsUrl = confirmed.wsUrl ?: resolved?.wsUrl ?: wsUrl
        ticket = confirmed.wsToken
        ticketExpiresAt = System.currentTimeMillis() + (confirmed.expiresIn ?: 60) * 1000
        paired = true
        if (pairingId.isNotEmpty() && deviceSecret.isNotEmpty()) {
            credentials.savePairedIdentity(pairingId, deviceSecret)
        }
    }

    fun clear() {
        paired = false
        wsUrl = ""
        ticket = ""
        ticketExpiresAt = 0
        pairingId = ""
    }

    private inline fun <reified T> decode(raw: String): T =
        json.decodeFromString(raw)

    // 后端字段蛇形命名，响应信封已由 unwrapData 剥离
    @kotlinx.serialization.Serializable
    private data class ResolvedWire(
        @kotlinx.serialization.SerialName("ws_url") val wsUrl: String? = null,
        @kotlinx.serialization.SerialName("pairing_id") val pairingId: String? = null,
        @kotlinx.serialization.SerialName("expires_in") val expiresIn: Int? = null,
        val status: String? = null,
    )

    @kotlinx.serialization.Serializable
    private data class ConfirmedWire(
        @kotlinx.serialization.SerialName("ws_token") val wsToken: String,
        @kotlinx.serialization.SerialName("ws_url") val wsUrl: String? = null,
        @kotlinx.serialization.SerialName("expires_in") val expiresIn: Int? = null,
        @kotlinx.serialization.SerialName("device_secret") val deviceSecret: String? = null,
        @kotlinx.serialization.SerialName("pairing_id") val pairingId: String? = null,
    )

    @kotlinx.serialization.Serializable
    private data class RefreshedWire(
        @kotlinx.serialization.SerialName("connect_ticket") val connectTicket: String,
        @kotlinx.serialization.SerialName("pairing_id") val pairingId: String? = null,
        @kotlinx.serialization.SerialName("expires_in") val expiresIn: Int? = null,
    )
}
