package top.neurova.mobile.core.service

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import top.neurova.mobile.core.accessibility.ExecutorGate
import top.neurova.mobile.core.capability.DeviceActionExecutor
import top.neurova.mobile.core.capability.DeviceCommandDispatcher
import top.neurova.mobile.core.capability.ExecuteOutcome
import top.neurova.mobile.core.protocol.DeviceBridgeEvents
import top.neurova.mobile.core.protocol.DeviceCommand
import top.neurova.mobile.core.protocol.DeviceTaskWindow

/** P2-24 生产装配判据：能力授权 → 任务窗口武装 → Dispatcher → 执行器。 */
class DeviceBridgeCommandCoordinatorTest {
    private class ProbeExecutor : DeviceActionExecutor {
        override val action = "screen_observe"
        var calls = 0
        override suspend fun execute(payload: JsonObject): ExecuteOutcome {
            calls += 1
            return ExecuteOutcome.ok()
        }
    }

    @Test
    fun rejectedForeignTaskDoesNotDisarmCurrentWindow() = runBlocking {
        val now = 4_000_000_000_000L
        val gate = ExecutorGate(clock = { now })
        gate.arm("task-1", now + 60_000)
        val coordinator = DeviceBridgeCommandCoordinator(
            isCapabilityEnabled = { true },
            gate = gate,
            dispatcher = DeviceCommandDispatcher(emptyList(), gate = gate, clock = { now }),
            clock = { now },
        )
        coordinator.onTask(DeviceTaskWindow(
            action = "start", taskId = "task-2", status = "error",
            expiresAt = 0, errorCode = "task_window_busy",
        ))
        assertTrue(gate.isArmed("task-1"))
        Unit
    }

    @Test
    fun capabilityAuthorizationThenTaskWindowArmsDispatcher() = runBlocking {
        var now = 4_000_000_000_000L
        val gate = ExecutorGate(clock = { now })
        val executor = ProbeExecutor()
        val coordinator = DeviceBridgeCommandCoordinator(
            isCapabilityEnabled = { it == "screen_observe" },
            gate = gate,
            dispatcher = DeviceCommandDispatcher(listOf(executor), gate = gate, clock = { now }),
            clock = { now },
        )
        val command = DeviceCommand(
            commandId = "cmd-1", action = "screen_observe", payload = JsonObject(emptyMap()),
            taskId = "task-1", windowExpiresAt = now + 60_000,
        )
        assertTrue(coordinator.handle(command)["status"]?.toString()?.contains("error") == true)
        assertEquals(0, executor.calls)

        coordinator.onTask(DeviceBridgeEvents.parseTaskWindow(
            JsonObject(mapOf(
                "type" to JsonPrimitive("device:task"),
                "action" to JsonPrimitive("start"),
                "task_id" to JsonPrimitive("task-1"),
                "status" to JsonPrimitive("active"),
                "expires_at" to JsonPrimitive((now + 60_000) / 1000.0),
            )),
        )!!)
        assertTrue(gate.isArmed("task-1"))
        assertEquals("ok", coordinator.handle(command)["status"]?.toString()?.trim('"'))
        assertEquals(1, executor.calls)

        now += 60_001
        assertFalse(gate.isArmed("task-1"))
        Unit
    }
}
