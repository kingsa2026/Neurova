package top.neurova.mobile.core.service

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import top.neurova.mobile.core.accessibility.ExecutorGate
import top.neurova.mobile.core.capability.DeviceCommandDispatcher
import top.neurova.mobile.core.protocol.DeviceBridgeEvents
import top.neurova.mobile.core.protocol.DeviceCommand
import top.neurova.mobile.core.protocol.DeviceTaskWindow

/** 设备桥生产授权装配：能力开关 → 服务端任务窗口 → Dispatcher → 屏幕执行器。 */
class DeviceBridgeCommandCoordinator(
    private val isCapabilityEnabled: (String) -> Boolean,
    private val gate: ExecutorGate,
    private val dispatcher: DeviceCommandDispatcher,
    private val clock: () -> Long = System::currentTimeMillis,
    private val onActivity: (String) -> Unit = {},
) {
    fun onTask(window: DeviceTaskWindow) {
        if (window.status == "active" && window.expiresAt > clock()) {
            gate.arm(window.taskId, window.expiresAt)
            return
        }
        // 外地任务被互斥拒绝时不能解除当前窗口；只有归属当前任务的结束/失效
        // 才解除，避免第二次开始任务把第一个任务一并 disarm。
        if (gate.isArmed(window.taskId) && window.errorCode != "task_window_busy") {
            gate.disarm()
        }
    }

    fun handle(command: DeviceCommand): JsonObject {
        if (!isCapabilityEnabled(command.action)) {
            return error(command.commandId, "capability_disabled", "该能力未在手机端授权")
        }
        if (command.taskId.isBlank() || command.windowExpiresAt <= clock() || !gate.isArmed(command.taskId)) {
            return error(command.commandId, "task_window_required", "显式任务窗口无效或已到期")
        }
        val result = dispatcher.handleExecute(command)
        val errorCode = ((result["error"] as? JsonObject)?.get("code") as? JsonPrimitive)?.contentOrNull
        if (errorCode == "executor_error") gate.disarm()
        if (errorCode == null && gate.isArmed(command.taskId)) onActivity(command.taskId)
        return result
    }

    private fun error(commandId: String, code: String, message: String): JsonObject =
        DeviceBridgeEvents.buildResult(
            commandId, "error", JsonObject(emptyMap()),
            JsonObject(mapOf(
                "code" to JsonPrimitive(code),
                "message" to JsonPrimitive(message),
            )),
        )
}
