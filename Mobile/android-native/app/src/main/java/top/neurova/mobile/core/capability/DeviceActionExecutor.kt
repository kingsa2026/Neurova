package top.neurova.mobile.core.capability

import kotlinx.serialization.json.JsonObject

/**
 * 设备桥能力词表与执行器契约（2026-11-23 计划卡 A3；词表与后端
 * tunnel/protocol.DEVICE_CAPABILITIES 同源，端上只宣称已实现的子集）。
 */
object DeviceCapabilities {
    const val PLATFORM = "android"
    const val PROTOCOL_VERSION = 1

    /** P0 端上已实现并对外宣称的能力（notification_read 随 A5 监听器批宣称，screen_* 随 A4） */
    val CLAIMED = listOf(
        "open_url", "open_app", "clipboard_read", "clipboard_write",
        "app_list", "device_env",
    )

    /**
     * 后台不可靠动作（对齐后端 router.BACKGROUND_UNSAFE_ACTIONS）：安卓 10+
     * 后台启动 Activity 受限、后台读剪贴板有前台判定。app_state != foreground
     * 时收到这些动作直接结构化拒绝，绝不假装执行。
     */
    val BACKGROUND_UNSAFE = setOf(
        "open_url", "open_app", "clipboard_read", "screen_observe", "screen_gesture",
    )
}

/** 单条命令的执行结局：ok 携 data；error 携结构化 code/message（诚实失败面） */
data class ExecuteOutcome(
    val status: String,
    val data: JsonObject = JsonObject(emptyMap()),
    val errorCode: String? = null,
    val errorMessage: String? = null,
) {
    companion object {
        fun ok(data: JsonObject = JsonObject(emptyMap())): ExecuteOutcome =
            ExecuteOutcome(status = "ok", data = data)

        fun error(code: String, message: String): ExecuteOutcome =
            ExecuteOutcome(status = "error", errorCode = code, errorMessage = message)
    }
}

/** 能力执行器：一个 action 一个执行器；执行在调用方协程上，允许挂起 */
interface DeviceActionExecutor {
    val action: String

    suspend fun execute(payload: JsonObject): ExecuteOutcome
}
