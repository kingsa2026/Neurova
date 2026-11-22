package top.neurova.mobile.core.protocol

import java.security.SecureRandom
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * 隧道准入令牌定型签发（U9/U16 口径，与后端 `neurova/tunnel/protocol.py` 的
 * `signTunnelToken` 单源同式）：
 *
 * 信封 `nv1:{type}:{issuedAt}:{nonce}` ＋ HMAC-SHA256(secret, 信封)，
 * 令牌全文 `nv1:{type}:{issuedAt}:{nonce}:{hmac}`。
 *
 * - 移动端数据面 type=agent；
 * - 原始密钥只参与签名、不再上线（裸密钥放 auth 消息属 legacy 降级形态，
 *   正解是本地签 nv1 信封）；
 * - 已带 `nv1:` 前缀的令牌（已有信封）原样使用，不二次签发。
 */
object TunnelTokenSigner {

    const val ENVELOPE = "nv1"
    const val TYPE_AGENT = "agent"
    const val TYPE_USER = "user"
    const val TYPE_SERVICE = "service"

    private val VALID_TYPES = setOf(TYPE_AGENT, TYPE_USER, TYPE_SERVICE)

    /** 是否已是定型信封（`nv1:` 前缀）——是则调用方原样用，不再签 */
    fun isEnveloped(token: String?): Boolean =
        !token.isNullOrEmpty() && token.startsWith("$ENVELOPE:")

    /**
     * 签发定型令牌。issuedAtSeconds/nonce 可注入以对拍（生产缺省取当前时刻＋
     * CSPRNG 16 位十六进制 nonce，与 python `secrets.token_hex(8)` 同形）。
     */
    fun signTunnelToken(
        secret: String,
        tokenType: String = TYPE_AGENT,
        issuedAtSeconds: Long = System.currentTimeMillis() / 1000,
        nonce: String = randomNonce(),
    ): String {
        require(tokenType in VALID_TYPES) { "未知令牌型 $tokenType（须为 agent/user/service）" }
        require(secret.isNotEmpty()) { "签发定型令牌必须提供密钥（空密钥等于任何人都能自签）" }
        val message = "$ENVELOPE:$tokenType:$issuedAtSeconds:$nonce"
        return "$message:${hmacSha256Hex(secret, message)}"
    }

    /** HMAC-SHA256 → 小写十六进制（对齐 python hmac.hexdigest()） */
    internal fun hmacSha256Hex(secret: String, message: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(secret.toByteArray(Charsets.UTF_8), "HmacSHA256"))
        return mac.doFinal(message.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
    }

    private fun randomNonce(): String {
        val bytes = ByteArray(8)
        SecureRandom().nextBytes(bytes)
        return bytes.joinToString("") { "%02x".format(it) }
    }
}
