package top.neurova.mobile.core.capability

import top.neurova.mobile.feature.servers.PreferencesStore

/**
 * 端上能力授权仓（2026-11-23 计划卡 A6；D4 红线：端上能力默认全关）。
 *
 * - 逐能力开关：默认**全关**——device:hello 只上报用户开启的子集，未开启的
 *   动作在端上直接拒绝（capability_disabled），与后端总闸构成双闸；
 * - 通知白名单（D3）：空 = 全量采集，配置后仅采集名单内应用；
 * - 敏感应用附加名单：在 SensitiveAppGuard 默认名单之上追加。
 */
class DeviceAuthStore(private val preferences: PreferencesStore) {

    fun enabledCapabilities(): Set<String> =
        split(preferences.readString(KEY_ENABLED))

    fun isEnabled(action: String): Boolean = action in enabledCapabilities()

    fun setEnabled(action: String, enabled: Boolean) {
        val current = enabledCapabilities().toMutableSet()
        if (enabled) {
            current.add(action)
        } else {
            current.remove(action)
        }
        preferences.writeString(KEY_ENABLED, join(current))
    }

    fun notificationWhitelist(): Set<String> = split(preferences.readString(KEY_WHITELIST))

    fun setNotificationWhitelist(packages: Set<String>) {
        preferences.writeString(KEY_WHITELIST, join(packages))
    }

    fun sensitiveExtras(): Set<String> = split(preferences.readString(KEY_SENSITIVE))

    fun addSensitivePackage(packageName: String) {
        val current = sensitiveExtras().toMutableSet()
        current.add(packageName)
        preferences.writeString(KEY_SENSITIVE, join(current))
    }

    private fun join(values: Set<String>): String = values.filter { it.isNotBlank() }.sorted().joinToString(",")

    private fun split(raw: String?): Set<String> =
        (raw ?: "").split(",").map { it.trim() }.filter { it.isNotEmpty() }.toSet()

    companion object {
        const val KEY_ENABLED = "device_bridge.enabled_capabilities"
        const val KEY_WHITELIST = "device_bridge.notification_whitelist"
        const val KEY_SENSITIVE = "device_bridge.sensitive_extra"
    }
}
