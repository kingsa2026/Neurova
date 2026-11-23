package top.neurova.mobile.core.notification

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 通知采集判据（2026-11-23 计划卡 A5；D3 拍板：全量采集+白名单授权）：
 * - 事件环有界（容量截断最旧）、按 id 去重、空包名拒收；
 * - 白名单为空 = 全放行；配置后仅放行名单内应用；
 * - device:event 批次帧与 device_notification_read 回执形状固定。
 */
class NotificationRingTest {

    private fun item(
        id: String,
        packageName: String = "com.example.app",
        title: String = "标题",
        text: String = "正文",
        postedAt: Long = 1000L,
    ) = NotificationItem(id = id, packageName = packageName, title = title,
        text = text, postedAt = postedAt)

    @Test
    fun ring_isBoundedAndDropsOldest() {
        val ring = NotificationRing(capacity = 3)
        for (i in 1..5) {
            ring.add(item(id = "n$i", postedAt = i.toLong()))
        }
        val snapshot = ring.snapshot(limit = 10)
        assertEquals(listOf("n3", "n4", "n5"), snapshot.map { it.id })
    }

    @Test
    fun ring_deduplicatesById() {
        val ring = NotificationRing(capacity = 5)
        assertTrue(ring.add(item(id = "dup")))
        assertFalse(ring.add(item(id = "dup")))
        assertEquals(1, ring.size())
    }

    @Test
    fun ring_rejectsEmptyPackage() {
        val ring = NotificationRing(capacity = 5)
        assertFalse(ring.add(item(id = "n1", packageName = "")))
    }

    @Test
    fun whitelist_emptyMeansAllowAll_configuredMeansOnlyListed() {
        val ring = NotificationRing(capacity = 5)
        assertTrue(ring.add(item(id = "a", packageName = "com.any.app")))

        ring.whitelist = setOf("com.allowed.app")
        assertFalse(ring.add(item(id = "b", packageName = "com.any.app")))
        assertTrue(ring.add(item(id = "c", packageName = "com.allowed.app")))
    }

    @Test
    fun batchFrame_hasFixedShape() {
        val frame = NotificationEvents.buildBatchFrame(listOf(item(id = "n1")))
        assertEquals("device:event", frame["type"]?.toString()?.trim('"'))
        assertEquals("notification_batch", frame["event_kind"]?.toString()?.trim('"'))
        assertTrue(frame["items"].toString().contains("com.example.app"))
    }

    @Test
    fun readData_carriesItemsForPullTool() {
        val data = NotificationEvents.buildReadData(listOf(item(id = "n1", title = "t")))
        assertTrue(data["items"].toString().contains("\"t\""))
    }
}
