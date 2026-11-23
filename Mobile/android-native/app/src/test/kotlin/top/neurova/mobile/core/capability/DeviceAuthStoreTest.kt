package top.neurova.mobile.core.capability

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import top.neurova.mobile.core.accessibility.SensitiveAppGuard

/**
 * 端上能力授权仓判据（2026-11-23 计划卡 A6；D4 红线：端上能力默认全关）：
 * - 默认全部关闭（hello 目录因此为空，直到用户逐能力开启）；
 * - 开关持久化（重开进程保持）；
 * - 通知白名单与敏感应用附加名单持久化。
 */
class DeviceAuthStoreTest {

    private class FakePreferences : top.neurova.mobile.feature.servers.PreferencesStore {
        val values = HashMap<String, String>()
        override fun readString(key: String): String? = values[key]
        override fun writeString(key: String, value: String) {
            values[key] = value
        }
    }

    private fun store(): DeviceAuthStore = DeviceAuthStore(FakePreferences())

    @Test
    fun store_defaultAllDisabled() {
        val s = store()
        for (action in DeviceCapabilities.CLAIMED) {
            assertFalse("action=$action", s.isEnabled(action))
        }
        assertTrue(s.enabledCapabilities().isEmpty())
    }

    @Test
    fun store_enableDisableRoundTrip() {
        val s = store()
        s.setEnabled("open_url", true)
        s.setEnabled("device_env", true)
        assertTrue(s.isEnabled("open_url"))
        s.setEnabled("open_url", false)
        assertFalse(s.isEnabled("open_url"))
        assertTrue(s.isEnabled("device_env"))
    }

    @Test
    fun store_notificationWhitelistRoundTrip() {
        val s = store()
        assertTrue(s.notificationWhitelist().isEmpty())
        s.setNotificationWhitelist(setOf("com.allowed.app"))
        assertEquals(setOf("com.allowed.app"), s.notificationWhitelist())
    }

    @Test
    fun store_sensitiveExtrasRoundTrip() {
        val s = store()
        assertFalse(SensitiveAppGuard.isHidden("com.custom.bank", s.sensitiveExtras()))
        s.addSensitivePackage("com.custom.bank")
        assertTrue(SensitiveAppGuard.isHidden("com.custom.bank", s.sensitiveExtras()))
    }
}
