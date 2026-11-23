package top.neurova.mobile.core.accessibility

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 凭据防线与敏感应用隐身判据（2026-11-23 计划卡 A4/M3 安全底线）：
 * - 密码字段（isPassword）与验证码语境字段禁止注入/禁止出文本；
 * - 金融/密码管理类应用默认隐身（无元素、无投影）。
 */
class GuardsTest {

    private fun node(
        label: String = "",
        text: String = "",
        isPassword: Boolean = false,
    ) = ScreenNode(role = "input", label = label, text = text, isPassword = isPassword)

    @Test
    fun credentialGuard_passwordFieldIsAlwaysCredential() {
        assertTrue(CredentialGuard.isCredentialField(node(label = "密码", isPassword = true)))
    }

    @Test
    fun credentialGuard_verificationCodeContextIsCredential() {
        assertTrue(CredentialGuard.isCredentialField(node(label = "验证码", text = "")))
        assertTrue(CredentialGuard.isCredentialField(node(label = "短信验证码", text = "123456")))
        assertTrue(CredentialGuard.isCredentialField(node(label = "Email", text = "verification code: 998877")))
        assertTrue(CredentialGuard.isCredentialField(node(label = "otp")))
    }

    @Test
    fun credentialGuard_normalFieldsPass() {
        assertFalse(CredentialGuard.isCredentialField(node(label = "用户名", text = "neo")))
        assertFalse(CredentialGuard.isCredentialField(node(label = "搜索", text = "订单 12345678")))
        assertFalse(CredentialGuard.isCredentialField(node(label = "收货地址")))
    }

    @Test
    fun sensitiveAppGuard_hidesFinanceAndPasswordAppsByDefault() {
        assertTrue(SensitiveAppGuard.isHidden("com.eg.android.AlipayGphone"))
        assertTrue(SensitiveAppGuard.isHidden("com.unionpay"))
        assertTrue(SensitiveAppGuard.isHidden("com.lastpass.lpandroid"))
        assertFalse(SensitiveAppGuard.isHidden("com.tencent.mm"))
        assertFalse(SensitiveAppGuard.isHidden("org.mozilla.firefox"))
    }

    @Test
    fun sensitiveAppGuard_extraListIsHonored() {
        assertTrue(SensitiveAppGuard.isHidden("com.custom.bank", extra = setOf("com.custom.bank")))
        assertFalse(SensitiveAppGuard.isHidden("com.custom.bank"))
    }
}
