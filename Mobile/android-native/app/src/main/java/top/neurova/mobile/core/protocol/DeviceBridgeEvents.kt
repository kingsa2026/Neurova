package top.neurova.mobile.core.protocol

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.doubleOrNull

/**
 * 设备桥协议帧解析/构造（2026-11-23 计划卡 A2；帧型字面量与后端
 * tunnel/protocol.py 的 device: 帧族同源，勿在此另起命名）。
 *
 * 手机侧职责：收 `device:execute` → 能力执行器执行 → 回 `device:result`；
 * 连接后先发 `device:hello` 自报能力快照（能力协商的端侧半边）。
 */
data class DeviceCommand(
    val commandId: String,
    val action: String,
    val payload: JsonObject,
    val timeoutMs: Long? = null,
    val intent: String? = null,
    val taskId: String = "",
    val windowExpiresAt: Long = 0,
)

data class DeviceTaskWindow(
    val action: String,
    val taskId: String,
    val status: String,
    val expiresAt: Long,
    val errorCode: String = "",
)

object DeviceBridgeEvents {

    /** 解析 `device:execute`；缺 command_id/action 或类型不符返回 null（不猜） */
    fun parseExecute(frame: JsonObject): DeviceCommand? {
        if (frame.typeName() != "device:execute") return null
        val commandId = frame.text("command_id")
        val action = frame.text("action")
        if (commandId.isEmpty() || action.isEmpty()) return null
        val payload = frame["payload"] as? JsonObject ?: JsonObject(emptyMap())
        val timeoutMs = (frame["timeout_ms"] as? JsonPrimitive)?.longOrNull
        val intent = frame.text("intent")
        return DeviceCommand(
            commandId = commandId,
            action = action,
            payload = payload,
            timeoutMs = timeoutMs,
            intent = intent?.takeIf { it.isNotEmpty() },
            taskId = frame.text("task_id"),
            windowExpiresAt = frame.deadlineMillis("window_expires_at", "expires_at"),
        )
    }

    fun parseTaskWindow(frame: JsonObject): DeviceTaskWindow? {
        if (frame.typeName() != "device:task") return null
        val taskId = frame.text("task_id")
        if (taskId.isEmpty()) return null
        val serverExpiresAt = frame.deadlineMillis("expires_at", "window_expires_at")
        return DeviceTaskWindow(
            action = frame.text("action"),
            taskId = taskId,
            status = frame.text("status"),
            expiresAt = serverExpiresAt,
            errorCode = frame.text("code"),
        )
    }

    fun buildTask(action: String, taskId: String, appState: String): JsonObject = JsonObject(
        linkedMapOf(
            "type" to JsonPrimitive("device:task"),
            "action" to JsonPrimitive(action),
            "task_id" to JsonPrimitive(taskId),
            "app_state" to JsonPrimitive(appState),
        ),
    )

    /** 构造 `device:result` 回执（status=ok/error；error 仅失败时随行） */
    fun buildResult(
        commandId: String,
        status: String,
        data: JsonObject,
        error: JsonObject?,
    ): JsonObject {
        val map = linkedMapOf<String, JsonElement>(
            "type" to JsonPrimitive("device:result"),
            "command_id" to JsonPrimitive(commandId),
            "status" to JsonPrimitive(status),
            "data" to data,
        )
        if (error != null) map["error"] = error
        return JsonObject(map)
    }

    /** 构造 `device:hello` 能力快照帧（连接建立后与能力变化时上报） */
    fun buildHello(
        platform: String,
        protocolVersion: Int,
        capabilities: List<String>,
        appState: String,
    ): JsonObject = JsonObject(
        linkedMapOf(
            "type" to JsonPrimitive("device:hello"),
            "platform" to JsonPrimitive(platform),
            "protocol_version" to JsonPrimitive(protocolVersion),
            "capabilities" to JsonArray(capabilities.map { JsonPrimitive(it) }),
            "app_state" to JsonPrimitive(appState),
        ),
    )
}

/** 帧类型字段读取（JsonPrimitive 去引号；与 ToolActionEvents 同一容错口径） */
internal fun JsonObject.typeName(): String? = text("type")

internal fun JsonObject.text(key: String): String {
    val primitive = this[key] as? JsonPrimitive ?: return ""
    return primitive.content
}

/** 后端期限为 Unix 秒（可带小数）；兼容早期毫秒整数帧。 */
internal fun JsonObject.deadlineMillis(vararg keys: String): Long {
    for (key in keys) {
        val primitive = this[key] as? JsonPrimitive ?: continue
        primitive.longOrNull?.let { return if (it < 100_000_000_000L) it * 1000 else it }
        primitive.doubleOrNull?.let { return (it * 1000).toLong() }
    }
    return 0
}
