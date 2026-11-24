package top.neurova.mobile.core.protocol

/**
 * 配对深链解析（两端同一事实源：《中继方案》§3.4 协议 neurova://pair?ref=…&host=…）。
 * 只认 neurova://pair 精确路径（拒绝 neurova://pairing 等前缀碰撞），ref 非空才有效；
 * 非 neurova scheme（如 https 落入浏览器）一律拒绝，不猜测变体。
 */
object PairingRefParser {

    private val PAIR_URI = Regex("^neurova://pair(\\?|$)", RegexOption.IGNORE_CASE)

    fun parseRef(uri: String): String? {
        val trimmed = uri.trim()
        if (!PAIR_URI.containsMatchIn(trimmed)) return null
        val queryIndex = trimmed.indexOf('?')
        if (queryIndex < 0) return null
        return trimmed.substring(queryIndex + 1)
            .split('&')
            .firstOrNull { it.startsWith("ref=", ignoreCase = true) }
            ?.substring(4)
            ?.takeIf { it.isNotBlank() }
    }

    /**
     * 深链 host 参数（一扫配全，2026-11-16 用户裁定；对齐鸿蒙端
     * PairingPayload.HOST_PATTERN）：URL 编码的对外地址，解码后返回；
     * 缺失/空/非 neurova://pair 均返回 null（调用方保持现档案）。
     */
    fun parseHost(uri: String): String? {
        val trimmed = uri.trim()
        if (!PAIR_URI.containsMatchIn(trimmed)) return null
        val queryIndex = trimmed.indexOf('?')
        if (queryIndex < 0) return null
        return trimmed.substring(queryIndex + 1)
            .split('&')
            .firstOrNull { it.startsWith("host=", ignoreCase = true) }
            ?.substring(5)
            ?.takeIf { it.isNotBlank() }
            ?.let { java.net.URLDecoder.decode(it, "UTF-8") }
    }
}
