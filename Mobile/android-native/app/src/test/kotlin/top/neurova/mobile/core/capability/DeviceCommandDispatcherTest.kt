package top.neurova.mobile.core.capability

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 设备命令派发器判据（2026-11-23 计划卡 A3）：
 * - 动作路由到对应执行器；未知动作结构化拒绝（unsupported_method）；
 * - 后台不可靠动作在 app_state != foreground 时拒绝（background_unavailable），
 *   安全动作后台照常执行（对齐后端能力协商语义）；
 * - 同 command_id 重放不重复执行（断线重连重放防线），回执带 replayed 标记；
 * - 执行器失败 → 诚实 error 回执（code/message 透传）；
 * - 非设备帧不消费（返回 null，交回既有聊天分发）。
 */
class DeviceCommandDispatcherTest {

    private class FakeExecutor(
        override val action: String,
        private val outcome: ExecuteOutcome,
    ) : DeviceActionExecutor {
        val calls = mutableListOf<JsonObject>()

        override suspend fun execute(payload: JsonObject): ExecuteOutcome {
            calls.add(payload)
            return outcome
        }
    }

    private fun frame(raw: String): JsonObject =
        Json.parseToJsonElement(raw).jsonObject

    private fun dispatcher(
        executors: List<DeviceActionExecutor>,
        appState: String = "foreground",
    ): DeviceCommandDispatcher {
        val gate = top.neurova.mobile.core.accessibility.ExecutorGate(
            clock = { 4_000_000_000_000L },
        )
        gate.arm(taskId = "task-1", expiresAt = 4_102_444_800_000L)
        return DeviceCommandDispatcher(
            executors = executors.associateBy { it.action },
            appStateProvider = { appState },
            gate = gate,
            clock = { 4_000_000_000_000L },
        )
    }

    private fun executeFrame(action: String, commandId: String = "dev-1", payload: String = "{}") =
        frame(
            """{"type":"device:execute","command_id":"$commandId","action":"$action",
               "task_id":"task-1","window_expires_at":4102444800000,
               "payload":$payload}""",
        )

    @Test
    fun dispatch_routesToExecutorAndBuildsOkResult() = kotlinx.coroutines.runBlocking {
        val executor = FakeExecutor(
            "open_url",
            ExecuteOutcome.ok(JsonObject(mapOf("opened" to JsonPrimitive(true)))),
        )
        val result = dispatcher(listOf(executor)).handleFrame(
            executeFrame("open_url", payload = """{"url":"https://example.com"}"""),
        )!!
        assertEquals(1, executor.calls.size)
        assertEquals("https://example.com", executor.calls[0]["url"]?.jsonPrimitive?.content)
        assertEquals("device:result", result["type"]?.toString()?.trim('"'))
        assertEquals("dev-1", result["command_id"]?.toString()?.trim('"'))
        assertEquals("ok", result["status"]?.toString()?.trim('"'))
        assertEquals(
            "true",
            (result["data"] as JsonObject)["opened"]?.toString()?.trim('"'),
        )
        Unit
    }

    @Test
    fun dispatch_unknownActionIsStructuredRefusal() = kotlinx.coroutines.runBlocking {
        val result = dispatcher(emptyList()).handleFrame(executeFrame("teleport"))!!
        assertEquals("error", result["status"]?.toString()?.trim('"'))
        assertEquals(
            "unsupported_method",
            (result["error"] as JsonObject)["code"]?.toString()?.trim('"'),
        )
        Unit
    }

    @Test
    fun dispatch_backgroundBlocksUnsafeActionButServesSafeOne() = kotlinx.coroutines.runBlocking {
        val executor = FakeExecutor("device_env", ExecuteOutcome.ok())
        val background = dispatcher(listOf(executor), appState = "background")

        val blocked = background.handleFrame(executeFrame("open_url", commandId = "dev-bg-1"))!!
        assertEquals(
            "background_unavailable",
            (blocked["error"] as JsonObject)["code"]?.toString()?.trim('"'),
        )

        val served = background.handleFrame(executeFrame("device_env", commandId = "dev-bg-2"))!!
        assertEquals("ok", served["status"]?.toString()?.trim('"'))
        assertEquals(1, executor.calls.size)
        Unit
    }

    @Test
    fun dispatch_duplicateCommandIsReplayedWithoutReexecution() = kotlinx.coroutines.runBlocking {
        val executor = FakeExecutor(
            "device_env",
            ExecuteOutcome.ok(JsonObject(mapOf("battery" to JsonPrimitive(0.5)))),
        )
        val d = dispatcher(listOf(executor))
        val first = d.handleFrame(executeFrame("device_env", commandId = "dev-dup"))!!
        val replayed = d.handleFrame(executeFrame("device_env", commandId = "dev-dup"))!!
        assertEquals(1, executor.calls.size)
        assertEquals(true, replayed["replayed"]?.toString()?.trim('"')?.toBoolean())
        assertEquals(
            (first["data"] as JsonObject)["battery"]?.toString(),
            (replayed["data"] as JsonObject)["battery"]?.toString(),
        )
        Unit
    }

    @Test
    fun dispatch_executorFailureIsHonestError() = kotlinx.coroutines.runBlocking {
        val executor = FakeExecutor(
            "clipboard_read",
            ExecuteOutcome.error("clipboard_denied", "系统拒绝"),
        )
        val result = dispatcher(listOf(executor))
            .handleFrame(executeFrame("clipboard_read", commandId = "dev-err"))!!
        assertEquals("error", result["status"]?.toString()?.trim('"'))
        val error = result["error"] as JsonObject
        assertEquals("clipboard_denied", error["code"]?.toString()?.trim('"'))
        assertEquals("系统拒绝", error["message"]?.toString()?.trim('"'))
        Unit
    }

    @Test
    fun dispatch_nonDeviceFrameIsIgnored() {
        val d = dispatcher(emptyList())
        assertNull(d.handleFrame(frame("""{"type":"chat:send","content":"hi"}""")))
    }

    @Test
    fun dispatch_missingTaskWindowIsRefusedBeforeExecutor() {
        val executor = FakeExecutor("device_env", ExecuteOutcome.ok())
        val result = dispatcher(listOf(executor)).handleFrame(
            frame("""{"type":"device:execute","command_id":"dev-no-task","action":"device_env","payload":{}}"""),
        )!!
        assertEquals("task_window_required", (result["error"] as JsonObject)["code"]?.toString()?.trim('"'))
        assertEquals(0, executor.calls.size)
    }

    @Test
    fun dispatch_malformedExecuteGetsMissingParamsRefusal() {
        val result = dispatcher(emptyList())
            .handleFrame(frame("""{"type":"device:execute","action":"open_url"}"""))!!
        assertEquals(
            "missing_params",
            (result["error"] as JsonObject)["code"]?.toString()?.trim('"'),
        )
    }
}
