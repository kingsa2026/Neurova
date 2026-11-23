package top.neurova.mobile.core.capability

import kotlinx.serialization.json.JsonObject
import top.neurova.mobile.core.protocol.DeviceBridgeEvents
import top.neurova.mobile.core.protocol.DeviceCommand

/**
 * 设备命令派发器（2026-11-23 计划卡 A3）：设备桥帧的端上执行咽喉。
 *
 * - 动作路由到对应 [DeviceActionExecutor]；未登记动作结构化拒绝
 *   （unsupported_method），不猜、不静默；
 * - 后台闸：app_state != foreground 时 BACKGROUND_UNSAFE 动作直接拒绝
 *   （background_unavailable）——能力协商的端侧运行半边；
 * - 同 command_id 重放不重复执行（断线重连重放防线）：已收敛命令的结果帧
 *   进 LRU 缓存，重放原样回执并附 replayed=true；
 * - 执行器失败 → 诚实 error 回执（code/message 透传，不吞不改）。
 */
class DeviceCommandDispatcher(
    private val executors: Map<String, DeviceActionExecutor>,
    private val appStateProvider: () -> String = { "foreground" },
    private val dedupCapacity: Int = DEFAULT_DEDUP_CAPACITY,
) {

    constructor(
        executors: List<DeviceActionExecutor>,
        appStateProvider: () -> String = { "foreground" },
        dedupCapacity: Int = DEFAULT_DEDUP_CAPACITY,
    ) : this(executors.associateBy { it.action }, appStateProvider, dedupCapacity)

    /** 已收敛命令的结果缓存（command_id → result 帧）：重连重放时原样回执 */
    private val settled = object : LinkedHashMap<String, JsonObject>(16, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, JsonObject>): Boolean =
            size > dedupCapacity
    }

    /** WS 帧入口：非设备桥帧返回 null（调用方继续走既有分发）；设备帧必回执 */
    fun handleFrame(frame: JsonObject): JsonObject? {
        if (frame["type"]?.toString()?.trim('"') != "device:execute") return null
        val command = DeviceBridgeEvents.parseExecute(frame)
            ?: return DeviceBridgeEvents.buildResult(
                commandId = frame["command_id"]?.toString()?.trim('"').orEmpty(),
                status = "error",
                data = JsonObject(emptyMap()),
                error = errorPayload("missing_params", "device:execute 缺 command_id/action"),
            )
        return handleExecute(command)
    }

    /** 执行一条命令并返回回执帧（同步执行器语义；挂起执行器走 handleFrameAsync） */
    fun handleExecute(command: DeviceCommand): JsonObject {
        synchronized(settled) {
            settled[command.commandId]?.let { previous ->
                return JsonObject(LinkedHashMap(previous).apply {
                    put("replayed", kotlinx.serialization.json.JsonPrimitive(true))
                })
            }
        }
        val result = executeNow(command)
        synchronized(settled) {
            settled[command.commandId] = result
        }
        return result
    }

    private fun executeNow(command: DeviceCommand): JsonObject {
        val appState = appStateProvider().ifEmpty { "foreground" }
        if (appState != "foreground" && command.action in DeviceCapabilities.BACKGROUND_UNSAFE) {
            return DeviceBridgeEvents.buildResult(
                command.commandId, "error", JsonObject(emptyMap()),
                errorPayload(
                    "background_unavailable",
                    "该动作在设备后台不可靠，需要回到前台执行",
                ),
            )
        }
        val executor = executors[command.action]
            ?: return DeviceBridgeEvents.buildResult(
                command.commandId, "error", JsonObject(emptyMap()),
                errorPayload(
                    "unsupported_method",
                    "端上未实现该能力：${command.action}",
                ),
            )
        val outcome = try {
            kotlinx.coroutines.runBlocking { executor.execute(command.payload) }
        } catch (e: Exception) {
            return DeviceBridgeEvents.buildResult(
                command.commandId, "error", JsonObject(emptyMap()),
                errorPayload("executor_error", e.message ?: e.javaClass.simpleName),
            )
        }
        return if (outcome.status == "ok") {
            DeviceBridgeEvents.buildResult(command.commandId, "ok", outcome.data, null)
        } else {
            DeviceBridgeEvents.buildResult(
                command.commandId, "error", outcome.data,
                errorPayload(
                    outcome.errorCode ?: "executor_error",
                    outcome.errorMessage ?: "执行失败",
                ),
            )
        }
    }

    private fun errorPayload(code: String, message: String): JsonObject = JsonObject(
        linkedMapOf(
            "code" to kotlinx.serialization.json.JsonPrimitive(code),
            "message" to kotlinx.serialization.json.JsonPrimitive(message),
        ),
    )

    companion object {
        const val DEFAULT_DEDUP_CAPACITY = 128
    }
}
