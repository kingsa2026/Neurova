package top.neurova.mobile.core.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 设备桥协议帧解析/构造判据（2026-11-23 计划卡 A2；帧型单源对齐后端
 * tunnel/protocol.py 的 device: 帧族）。
 */
class DeviceBridgeEventsTest {

    private val lenient = Json { ignoreUnknownKeys = true; isLenient = true }

    private fun frame(raw: String): JsonObject =
        lenient.parseToJsonElement(raw) as JsonObject

    @Test
    fun parseExecute_readsCommandFields() {
        val command = DeviceBridgeEvents.parseExecute(
            frame(
                """{"type":"device:execute","command_id":"dev-abc","action":"open_url",
                   "payload":{"url":"https://example.com"},"timeout_ms":8000,
                   "intent":"查看电池"}""",
            ),
        )
        assertNotNull(command)
        command!!
        assertEquals("dev-abc", command.commandId)
        assertEquals("open_url", command.action)
        assertEquals("https://example.com", command.payload["url"]?.toString()?.trim('"'))
        assertEquals(8000L, command.timeoutMs)
        assertEquals("查看电池", command.intent)
    }

    @Test
    fun parseExecute_rejectsWrongTypeAndMissingKeys() {
        assertNull(DeviceBridgeEvents.parseExecute(frame("""{"type":"chat:send"}""")))
        assertNull(
            DeviceBridgeEvents.parseExecute(
                frame("""{"type":"device:execute","action":"open_url"}"""),
            ),
        )
        assertNull(
            DeviceBridgeEvents.parseExecute(
                frame("""{"type":"device:execute","command_id":"dev-1"}"""),
            ),
        )
    }

    @Test
    fun buildResult_carriesCommandIdAndStatus() {
        val ok = DeviceBridgeEvents.buildResult(
            commandId = "dev-1",
            status = "ok",
            data = JsonObject(mapOf("battery" to JsonPrimitive(0.8))),
            error = null,
        )
        assertEquals("device:result", ok["type"]?.toString()?.trim('"'))
        assertEquals("dev-1", ok["command_id"]?.toString()?.trim('"'))
        assertEquals("ok", ok["status"]?.toString()?.trim('"'))

        val failed = DeviceBridgeEvents.buildResult(
            commandId = "dev-2",
            status = "error",
            data = JsonObject(emptyMap()),
            error = JsonObject(
                mapOf(
                    "code" to JsonPrimitive("clipboard_denied"),
                    "message" to JsonPrimitive("系统拒绝"),
                ),
            ),
        )
        assertEquals("error", failed["status"]?.toString()?.trim('"'))
        assertEquals(
            "clipboard_denied",
            (failed["error"] as JsonObject)["code"]?.toString()?.trim('"'),
        )
    }

    @Test
    fun buildHello_reportsPlatformCapabilitiesAppState() {
        val hello = DeviceBridgeEvents.buildHello(
            platform = "android",
            protocolVersion = 1,
            capabilities = listOf("open_url", "device_env"),
            appState = "foreground",
        )
        assertEquals("device:hello", hello["type"]?.toString()?.trim('"'))
        assertEquals("android", hello["platform"]?.toString()?.trim('"'))
        assertEquals(1, hello["protocol_version"]?.toString()?.trim('"')?.toInt())
        assertEquals("foreground", hello["app_state"]?.toString()?.trim('"'))
        val capabilities = hello["capabilities"].toString()
        assert(capabilities.contains("open_url") && capabilities.contains("device_env"))
    }
}
