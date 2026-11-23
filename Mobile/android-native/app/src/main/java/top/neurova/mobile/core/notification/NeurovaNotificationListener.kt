package top.neurova.mobile.core.notification

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

/**
 * 通知监听器（2026-11-23 计划卡 A5）：采集本机通知 → 事件环 → 经应用级 WS
 * 以 device:event 帧上报（有界批次）；同时供 device_notification_read 拉取。
 *
 * 白名单（D3）：默认全量采集，用户可在授权页配置应用白名单；
 * 用户未授权通知监听权限时本服务不会被系统拉起（能力自然降级）。
 */
class NeurovaNotificationListener : NotificationListenerService() {

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        if (sbn == null) return
        val extras = sbn.notification?.extras ?: return
        val title = extras.getCharSequence(android.app.Notification.EXTRA_TITLE)?.toString().orEmpty()
        val text = extras.getCharSequence(android.app.Notification.EXTRA_TEXT)?.toString().orEmpty()
        val packageName = sbn.packageName.orEmpty()
        val item = NotificationItem(
            id = "${packageName}|${sbn.id}|${sbn.postTime}|$title|$text",
            packageName = packageName,
            title = title,
            text = text,
            postedAt = sbn.postTime,
        )
        val accepted = NotificationRingHolder.ring.add(item)
        if (accepted) {
            flushOne(item)
        }
    }

    /** 单条即推（有界：一帧一条，积压由环承载）；失败留在环里随下一条重试 */
    private fun flushOne(item: NotificationItem) {
        val runtime = top.neurova.mobile.core.AppRuntime.instanceOrNull() ?: return
        val frame = NotificationEvents.buildBatchFrame(listOf(item))
        runtime.ws.sendDeviceFrame(frame)
    }

    companion object {
        /** 拉取式读数（device_notification_read 命令的端上数据源） */
        fun snapshot(limit: Int): List<NotificationItem> =
            NotificationRingHolder.ring.snapshot(limit)
    }
}

/** 进程级共享事件环（监听器与执行器/服务都取这里） */
object NotificationRingHolder {
    val ring = NotificationRing(capacity = 100)
}

/** device_notification_read 命令的端上执行器：从事件环拉取最近通知 */
class NotificationReadExecutor(private val defaultLimit: Int = 20) :
    top.neurova.mobile.core.capability.DeviceActionExecutor {

    override val action = "notification_read"

    override suspend fun execute(payload: kotlinx.serialization.json.JsonObject): top.neurova.mobile.core.capability.ExecuteOutcome {
        val requested = payload["limit"]?.toString()?.trim('"')?.toIntOrNull() ?: defaultLimit
        val items = NotificationRingHolder.ring.snapshot(requested)
        return top.neurova.mobile.core.capability.ExecuteOutcome.ok(
            NotificationEvents.buildReadData(items),
        )
    }
}
