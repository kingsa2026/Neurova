package top.neurova.mobile.core.accessibility

/**
 * 凭据防线（2026-11-23 计划卡 A4/M3 红线 1）：密码字段与验证码语境字段
 * **禁止注入、禁止出文本**；验证码数字在命中关键词语境下出端前打码。
 */
object CredentialGuard {

    /** 验证码语境关键词（中英；命中即视为凭据语境） */
    val CODE_KEYWORDS = listOf("验证码", "verification code", "otp", "安全码")

    /** 4 位及以上数字串（验证码典型 4-8 位；长串一并打码防泄漏长度） */
    private val CODE_DIGITS = Regex("\\d{4,}")

    fun isCredentialContext(vararg texts: String): Boolean =
        texts.any { text ->
            val lowered = text.lowercase()
            CODE_KEYWORDS.any { lowered.contains(it) }
        }

    /** 密码字段或验证码语境字段 = 凭据字段（注入与出文本都被拒） */
    fun isCredentialField(node: ScreenNode): Boolean =
        node.isPassword || isCredentialContext(node.label, node.text)

    /** 命中凭据语境时，把文本里的数字串逐位打码（• 与原等长，不泄长度） */
    fun maskCodeDigits(text: String, label: String = ""): String {
        if (!isCredentialContext(text, label)) {
            return text
        }
        return CODE_DIGITS.replace(text) { match -> "•".repeat(match.value.length) }
    }
}

/**
 * 敏感应用隐身（M3）：金融/支付/密码管理类应用默认隐身——读屏返回
 * hidden=true、手势拒绝执行。默认名单 + 用户可加（A6 授权页写入）。
 */
object SensitiveAppGuard {

    val DEFAULT_SENSITIVE: Set<String> = setOf(
        "com.eg.android.AlipayGphone",              // 支付宝
        "com.unionpay",                             // 云闪付
        "com.lastpass.lpandroid",                   // LastPass
        "com.x8bit.bitwarden",                      // Bitwarden
        "keepass2android.keepass2android",          // KeePass2Android
        "com.authy.authy",                          // Authy
        "com.google.android.apps.authenticator2",   // Google Authenticator
    )

    fun isHidden(packageName: String, extra: Set<String> = emptySet()): Boolean =
        packageName in DEFAULT_SENSITIVE || packageName in extra
}
