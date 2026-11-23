package top.neurova.mobile.core.push

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 推送唤醒判据（批三遗留清偿：B7 唤醒信令的端上接收）：
 * - FCM data 载荷 = 服务端 buildSignalingPayload 的键（notificationId/notificationType）；
 * - 仅 device_command_pending 触发 WS 唤醒（connectIfIdle + 续签由唤醒动作负责）；
 * - 其他类型/缺型/空载荷一律不唤醒（通知正文类推送走既有通知链，不打扰通道）。
 */
class DeviceWakeTest {

    @Test
    fun commandPendingWakesChannel() {
        var woke = 0
        val handled = DeviceWake.onSignaling(
            mapOf("notificationId" to "dev-1", "notificationType" to "device_command_pending"),
        ) { woke += 1 }
        assertTrue(handled)
        assertEquals(1, woke)
    }

    @Test
    fun otherTypesDoNotWake() {
        var woke = 0
        assertFalse(DeviceWake.onSignaling(
            mapOf("notificationId" to "n1", "notificationType" to "info")) { woke += 1 })
        assertFalse(DeviceWake.onSignaling(
            mapOf("notificationId" to "n2", "notificationType" to "approval_required")) { woke += 1 })
        assertEquals(0, woke)
    }

    @Test
    fun missingOrBlankTypeDoesNotWake() {
        var woke = 0
        assertFalse(DeviceWake.onSignaling(emptyMap()) { woke += 1 })
        assertFalse(DeviceWake.onSignaling(mapOf("notificationType" to "")) { woke += 1 })
        assertEquals(0, woke)
    }
}
