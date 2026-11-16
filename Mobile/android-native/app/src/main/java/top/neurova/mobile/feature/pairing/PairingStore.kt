package top.neurova.mobile.feature.pairing

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import java.util.UUID
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import top.neurova.mobile.core.net.HttpChannel
import top.neurova.mobile.core.protocol.ConfirmedWire
import top.neurova.mobile.core.protocol.PairingInput
import top.neurova.mobile.core.protocol.RefreshedWire
import top.neurova.mobile.core.protocol.ResolvedWire
import top.neurova.mobile.core.protocol.parsePairingInput
import top.neurova.mobile.core.protocol.pairingJson
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
    private val json = pairingJson
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

    /** 手动输入入口：6 位配对码与扫码 ref 分流（UI 承诺「粘贴 ref 或 6 位配对码」） */
    suspend fun pairByInput(input: String) {
        when (val parsed = parsePairingInput(input)) {
            is PairingInput.Code -> pairByCode(parsed.value)
            is PairingInput.Ref -> pairByRef(parsed.value)
            null -> return
        }
    }

    /** 一扫配全：resolve（ref 换回连地址）→ confirm（拿设备身份与一次性票据） */
    suspend fun pairByRef(ref: String) {
        val resolvedElement = http.unwrapData(
            http.postJson("/mobile/pairing/resolve", JsonObject(mapOf("ref" to JsonPrimitive(ref)))),
        )
        val resolved = decode<ResolvedWire>(resolvedElement.toString())
        completePairing(
            // 后端 ConfirmPairingRequest 是蛇形命名（device_name/device_type）——
            // 发驼峰会被 pydantic 静默忽略，设备名落不到登记表
            JsonObject(
                mapOf(
                    "ref" to JsonPrimitive(ref),
                    "device_name" to JsonPrimitive(deviceName()),
                    "device_type" to JsonPrimitive("android"),
                ),
            ),
            resolved,
        )
    }

    /** 手输 6 位码：免 resolve 直通 confirm（后端 confirm 收 ref/code 二选一，pending 可直接确认） */
    suspend fun pairByCode(code: String) {
        completePairing(
            JsonObject(
                mapOf(
                    "code" to JsonPrimitive(code),
                    "device_name" to JsonPrimitive(deviceName()),
                    "device_type" to JsonPrimitive("android"),
                ),
            ),
            null,
        )
    }

    private suspend fun completePairing(confirmBody: JsonObject, resolved: ResolvedWire?) {
        val confirmElement = http.unwrapData(http.postJson("/mobile/pairing/confirm", confirmBody))
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
        ticket = confirmed.connectTicket
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
}
