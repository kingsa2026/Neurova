package top.neurova.mobile.core.notification

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * 通知事件环与白名单过滤（2026-11-23 计划卡 A5；D3 拍板：全量采集 + 端上
 * 白名单授权，隐私控制放在授权层——白名单为空 = 全部放行，配置后仅放行名单内应用）。
 *
 * 纯逻辑无框架依赖（JVM 单测覆盖）；NotificationListenerService 是框架胶水。
 */
data class NotificationItem(
    val id: String,          // 去重键：package|title|text|postedAt
    val packageName: String,
    val title: String,
    val text: String,
    val postedAt: Long,
)

object NotificationWhitelist {

    /** 白名单为空 = 全部放行（D3：全量采集，隐私控制放授权层） */
    fun allowed(packageName: String, whitelist: Set<String>): Boolean =
        whitelist.isEmpty() || packageName in whitelist
}

class NotificationRing(private val capacity: Int = 100) {

    private val items = ArrayDeque<NotificationItem>()
    private val seen = HashSet<String>()

    @Synchronized
    fun add(item: NotificationItem): Boolean {
        if (item.packageName.isEmpty()) return false
        if (!NotificationWhitelist.allowed(item.packageName, whitelist)) return false
        if (!seen.add(item.id)) return false  // 重复通知不重复入环
        items.addLast(item)
        while (items.size > capacity) {
            val dropped = items.removeFirst()
            seen.remove(dropped.id)
        }
        return true
    }

    @Synchronized
    fun snapshot(limit: Int = 20): List<NotificationItem> =
        items.toList().takeLast(limit.coerceIn(1, capacity))

    @Synchronized
    fun drainPending(limit: Int = 20): List<NotificationItem> {
        val out = items.toList().takeLast(limit.coerceIn(1, capacity))
        return out
    }

    @Volatile
    var whitelist: Set<String> = emptySet()

    @Synchronized
    fun size(): Int = items.size
}

object NotificationEvents {

    /** device:event 帧（event_kind=notification_batch，有界条数） */
    fun buildBatchFrame(items: List<NotificationItem>): JsonObject = JsonObject(
        mapOf(
            "type" to JsonPrimitive("device:event"),
            "event_kind" to JsonPrimitive("notification_batch"),
            "items" to JsonArray(items.map { item ->
                JsonObject(
                    mapOf(
                        "id" to JsonPrimitive(item.id),
                        "package" to JsonPrimitive(item.packageName),
                        "title" to JsonPrimitive(item.title),
                        "text" to JsonPrimitive(item.text),
                        "posted_at" to JsonPrimitive(item.postedAt),
                    ),
                )
            }),
        ),
    )

    /** device_notification_read 命令的回执 data（拉取式读数） */
    fun buildReadData(items: List<NotificationItem>): JsonObject = JsonObject(
        mapOf(
            "items" to JsonArray(items.map { item ->
                JsonObject(
                    mapOf(
                        "package" to JsonPrimitive(item.packageName),
                        "title" to JsonPrimitive(item.title),
                        "text" to JsonPrimitive(item.text),
                        "posted_at" to JsonPrimitive(item.postedAt),
                    ),
                )
            }),
        ),
    )
}
