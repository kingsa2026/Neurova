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
}
