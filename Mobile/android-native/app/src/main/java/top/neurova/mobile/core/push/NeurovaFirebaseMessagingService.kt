package top.neurova.mobile.core.push

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import kotlinx.coroutines.launch
import top.neurova.mobile.core.AppRuntime

/**
 * FCM 推送接收（计划批三 B7 遗留清偿）：只消费**信令**（notificationId/type），
 * 正文不过推送通道。``device_command_pending`` → 唤醒设备桥 WS 通道
 * （connectIfIdle；空票由通道自举续签），让离线入队的遥控命令尽快补执行。
 *
 * Firebase 未配置（缺 google-services.json）时本服务不会被触发，App 零崩溃；
 * 凭据到位后自动生效，无需改码。
 */
class NeurovaFirebaseMessagingService : FirebaseMessagingService() {

    override fun onMessageReceived(message: RemoteMessage) {
        val data = message.data ?: return
        DeviceWake.onSignaling(data) {
            val runtime = AppRuntime.instanceOrNull() ?: return@onSignaling
            runtime.ws.connectIfIdle()
        }
    }

    override fun onNewToken(token: String) {
        super.onNewToken(token)
        // 令牌刷新：登录态就绪则择机重报（未登录时注册器会跳过，登录后由服务触发再报）
        runCatching {
            val runtime = AppRuntime.instance(this)
            runtime.scope.launch {
                runCatching { PushTokenRegistrar.registerIfNeeded(applicationContext, runtime) }
            }
        }
    }
}
