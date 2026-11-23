package top.neurova.mobile.core.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import top.neurova.mobile.R
import top.neurova.mobile.core.AppRuntime
import top.neurova.mobile.core.capability.AppStateTracker
import top.neurova.mobile.core.capability.AndroidDeviceExecutors
import top.neurova.mobile.core.capability.DeviceCapabilities
import top.neurova.mobile.core.capability.DeviceCommandDispatcher
import top.neurova.mobile.core.net.MobileWsChannel
import top.neurova.mobile.core.notification.NotificationRingHolder
import top.neurova.mobile.core.protocol.DeviceBridgeEvents

/**
 * 设备桥前台服务（2026-11-23 计划卡 A1/A5/A7）：应用级 WS 常连的承载者。
 *
 * - 退后台不断连（前台服务 + 常驻通知），执行端指令随时可达；
 * - 收 `device:execute` → 授权双检（D4：端上逐能力开关）→ 派发器执行
 *   （能力路由/后台闸/幂等去重）→ 同一 socket 回 `device:result`；
 *   AUTHED 时上报 `device:hello` 能力快照（仅含用户开启的子集）；
 * - 通知事件环白名单随授权页同步（A5）；命令执行时更新常驻通知进度（A7）；
 * - 复用 AppRuntime 的单一 WS 通道与配对装配——不另起第二套连接。
 */
class DeviceBridgeService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var jobs: List<Job> = emptyList()
    private var executedSteps = 0

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        ensureChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val runtime = AppRuntime.instanceOrNull() ?: AppRuntime.instance(this)
        startForeground(NOTIFICATION_ID, buildNotification())
        startBridge(runtime)
        return START_STICKY
    }

    override fun onDestroy() {
        jobs.forEach { it.cancel() }
        jobs = emptyList()
        scope.cancel()
        super.onDestroy()
    }

    private fun startBridge(runtime: AppRuntime) {
        if (jobs.isNotEmpty()) return
        val channel = runtime.ws
        val dispatcher = DeviceCommandDispatcher(
            executors = AndroidDeviceExecutors.all(this),
            appStateProvider = { AppStateTracker.current },
        )
        // A5：通知白名单随授权仓同步（空 = 全量采集）
        NotificationRingHolder.ring.whitelist = runtime.deviceAuth.notificationWhitelist()

        jobs = listOf(
            scope.launch {
                channel.events.collect { event ->
                    if (event is MobileWsChannel.Event.DeviceCommandArrived) {
                        val auth = runtime.deviceAuth
                        if (!auth.isEnabled(event.command.action)) {
                            // D4 双闸的端上半边：未授权能力直接拒绝
                            channel.sendDeviceFrame(
                                DeviceBridgeEvents.buildResult(
                                    event.command.commandId, "error",
                                    kotlinx.serialization.json.JsonObject(emptyMap()),
                                    kotlinx.serialization.json.JsonObject(
                                        mapOf(
                                            "code" to kotlinx.serialization.json.JsonPrimitive("capability_disabled"),
                                            "message" to kotlinx.serialization.json.JsonPrimitive(
                                                "该能力未在手机端授权（设备桥授权页可开启）"),
                                        ),
                                    ),
                                ),
                            )
                            return@collect
                        }
                        executedSteps += 1
                        updateProgressNotification(event.command.action, executedSteps)
                        channel.sendDeviceFrame(dispatcher.handleExecute(event.command))
                    }
                }
            },
            scope.launch {
                channel.state.collect { state ->
                    if (state == MobileWsChannel.State.AUTHED) {
                        val enabled = DeviceCapabilities.CLAIMED.filter {
                            runtime.deviceAuth.isEnabled(it)
                        }
                        channel.sendDeviceFrame(
                            DeviceBridgeEvents.buildHello(
                                platform = DeviceCapabilities.PLATFORM,
                                protocolVersion = DeviceCapabilities.PROTOCOL_VERSION,
                                capabilities = enabled,
                                appState = AppStateTracker.current,
                            ),
                        )
                    }
                }
            },
        )
        channel.connect()
    }

    private fun updateProgressNotification(action: String, steps: Int) {
        val manager = getSystemService(NotificationManager::class.java) ?: return
        manager.notify(
            NOTIFICATION_ID,
            NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle(getString(R.string.device_bridge_notification_title))
                .setContentText(getString(R.string.device_bridge_notification_running, "$action #$steps"))
                .setOngoing(true)
                .build(),
        )
    }

    private fun ensureChannel() {
        val manager = getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(CHANNEL_ID) == null) {
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "设备桥",
                    NotificationManager.IMPORTANCE_LOW,
                ),
            )
        }
    }

    private fun buildNotification(): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(getString(R.string.device_bridge_notification_title))
            .setContentText(getString(R.string.device_bridge_notification_idle))
            .setOngoing(true)
            .build()

    companion object {
        const val CHANNEL_ID = "device_bridge"
        const val NOTIFICATION_ID = 1001
    }
}
