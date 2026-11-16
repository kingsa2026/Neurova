package top.neurova.mobile.core.protocol

import kotlinx.serialization.json.Json

/**
 * 配对三口（resolve/confirm/refresh）的线上模型——字段名以后端
 * `neurova/api/endpoints/mobile_pairing.py` 的 pydantic 模型为唯一事实源（蛇形命名）。
 * 从 PairingStore 抽出为 internal：契约测试直接咬合真实响应形状，不必起后端。
 */
internal val pairingJson: Json = Json { ignoreUnknownKeys = true }

/** POST /mobile/pairing/resolve 的响应（pending → scanned；回连地址不含任何凭证） */
@kotlinx.serialization.Serializable
internal data class ResolvedWire(
    @kotlinx.serialization.SerialName("ws_url") val wsUrl: String? = null,
    @kotlinx.serialization.SerialName("pairing_id") val pairingId: String? = null,
    @kotlinx.serialization.SerialName("expires_in") val expiresIn: Int? = null,
    val status: String? = null,
)

/** POST /mobile/pairing/confirm 的响应（一次性接入凭证 + 长期设备身份） */
@kotlinx.serialization.Serializable
internal data class ConfirmedWire(
    @kotlinx.serialization.SerialName("connect_ticket") val connectTicket: String,
    @kotlinx.serialization.SerialName("ws_url") val wsUrl: String? = null,
    @kotlinx.serialization.SerialName("expires_in") val expiresIn: Int? = null,
    @kotlinx.serialization.SerialName("device_secret") val deviceSecret: String? = null,
    @kotlinx.serialization.SerialName("pairing_id") val pairingId: String? = null,
)

/** POST /mobile/pairing/refresh 的响应（只换 ticket，不改设备身份） */
@kotlinx.serialization.Serializable
internal data class RefreshedWire(
    @kotlinx.serialization.SerialName("connect_ticket") val connectTicket: String,
    @kotlinx.serialization.SerialName("pairing_id") val pairingId: String? = null,
    @kotlinx.serialization.SerialName("expires_in") val expiresIn: Int? = null,
)

/** 手动输入的两种入口：扫码 ref（22 位高熵串）与 6 位配对码 */
internal sealed class PairingInput {
    data class Ref(val value: String) : PairingInput()
    data class Code(val value: String) : PairingInput()
}

/**
 * 输入分流：6 位纯数字 = 配对码（confirm 的 code 口，免 resolve）；其余非空串按 ref 走。
 * 后端 resolve 只认高熵 ref 形状（isPairingRefShape），6 位码进 resolve 必 404——
 * 分流必须发生在客户端，UI 的「粘贴 ref 或 6 位配对码」承诺才成立。
 */
internal fun parsePairingInput(raw: String): PairingInput? {
    val value = raw.trim()
    if (value.isEmpty()) return null
    return if (value.length == 6 && value.all { it.isDigit() }) {
        PairingInput.Code(value)
    } else {
        PairingInput.Ref(value)
    }
}
