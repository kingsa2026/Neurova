package top.neurova.mobile.core.capability

import android.content.ComponentName
import android.content.Context
import android.provider.Settings
import androidx.core.app.NotificationManagerCompat
import top.neurova.mobile.core.accessibility.ExecutorAccessibilityService

/**
 * 设备桥体检项（2026-11-23 计划卡 A6）：端上执行能力的系统前置条件检查。
 * 全部是框架读数（不可 JVM 单测），供体检页/授权页呈现与引导。
 */
object DeviceHealthChecks {

    data class HealthItem(val key: String, val title: String, val ok: Boolean, val hint: String)

    /** 无障碍服务是否已在系统设置开启（读屏/手势能力的前置） */
    fun accessibilityEnabled(context: Context): Boolean {
        val manager = context.getSystemService(
            android.view.accessibility.AccessibilityManager::class.java,
        ) ?: return false
        val expected = ComponentName(context, ExecutorAccessibilityService::class.java)
            .flattenToString()
        return manager.getEnabledAccessibilityServiceList(
            android.accessibilityservice.AccessibilityServiceInfo.FEEDBACK_GENERIC,
        ).any {
            ComponentName(
                it.resolveInfo.serviceInfo.packageName,
                it.resolveInfo.serviceInfo.name,
            ).flattenToString() == expected
        }
    }

    /** 通知监听权限是否已授予（通知采集能力的前置） */
    fun notificationListenerEnabled(context: Context): Boolean =
        NotificationManagerCompat.getEnabledListenerPackages(context)
            .contains(context.packageName)

    /** 是否已加入电池优化白名单（常驻连接的稳定性前置） */
    fun isIgnoringBatteryOptimizations(context: Context): Boolean {
        val pm = context.getSystemService(android.os.PowerManager::class.java) ?: return false
        return pm.isIgnoringBatteryOptimizations(context.packageName)
    }

    /** 三项体检（授权页消费） */
    fun all(context: Context): List<HealthItem> = listOf(
        HealthItem(
            key = "accessibility",
            title = "无障碍执行器",
            ok = accessibilityEnabled(context),
            hint = "系统设置 → 无障碍 → Neurova（读屏与手势注入的前置）",
        ),
        HealthItem(
            key = "notification_listener",
            title = "通知监听",
            ok = notificationListenerEnabled(context),
            hint = "系统设置 → 通知使用权（通知采集的前置）",
        ),
        HealthItem(
            key = "battery",
            title = "电池优化白名单",
            ok = isIgnoringBatteryOptimizations(context),
            hint = "系统设置 → 电池 → 无限制（常驻连接稳定性）",
        ),
    )

    /** 体检引导用的系统设置跳转 action（页面消费） */
    const val ACTION_ACCESSIBILITY_SETTINGS = Settings.ACTION_ACCESSIBILITY_SETTINGS
    const val ACTION_NOTIFICATION_LISTENER_SETTINGS = "android.settings.NOTIFICATION_LISTENER_SETTINGS"
}
