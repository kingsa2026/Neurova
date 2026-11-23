package top.neurova.mobile.core.push

/**
 * 推送唤醒判定（计划批三 B7 遗留清偿）：FCM data 载荷即服务端
 * ``buildSignalingPayload`` 的键（notificationId / notificationType，
 * 信令-only，正文不过推送通道）。
 *
 * 仅 ``device_command_pending`` 触发 WS 唤醒（connectIfIdle + 续签由唤醒
 * 动作负责）；其余类型（站内通知等）走既有通知链，不打扰设备桥通道。
 */
object DeviceWake {
    const val TYPE_COMMAND_PENDING = "device_command_pending"

    /** 唤醒判定：命中命令待执行信令 → 执行 wake 并返回 true；其余类型返回 false。 */
    fun onSignaling(data: Map<String, String>, wake: () -> Unit): Boolean {
        val type = data["notificationType"]?.trim().orEmpty()
        if (type != TYPE_COMMAND_PENDING) {
            return false
        }
        wake()
        return true
    }
}
