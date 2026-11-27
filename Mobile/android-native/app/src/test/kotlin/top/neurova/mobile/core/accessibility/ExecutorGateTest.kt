package top.neurova.mobile.core.accessibility

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 无障碍执行器按需开关判据（2026-11-23 计划卡 A4/M1+红线 2）：
 * - 任务窗口内武装（接受命令），闲置 60s 自动解除；
 * - 显式 disarm 立即解除；每次命令活动续期；
 * - 解除后命令必须被拒绝（绝不常开）。
 */
class ExecutorGateTest {

    private fun gate(now: Long = 1_000_000L, idle: Long = 60_000L):
        Triple<ExecutorGate, () -> Long, (Long) -> Unit> {
        var clock = now
        val g = ExecutorGate(idleTimeoutMs = idle, clock = { clock })
        return Triple(g, { clock }, { value -> clock = value })
    }

    @Test
    fun gate_disarmedByDefault() {
        val (g, _, _) = gate()
        assertFalse(g.isArmed())
    }

    @Test
    fun gate_armedWithinWindowAndExpiresAfterIdle() {
        val (g, _, setClock) = gate(now = 1_000_000L, idle = 60_000L)
        g.arm()
        assertTrue(g.isArmed())
        setClock(1_000_000L + 59_999)
        assertTrue(g.isArmed())
        setClock(1_000_000L + 60_001)
        assertFalse(g.isArmed())
    }

    @Test
    fun gate_explicitDisarmIsImmediate() {
        val (g, _, _) = gate()
        g.arm()
        assertTrue(g.isArmed())
        g.disarm()
        assertFalse(g.isArmed())
    }

    @Test
    fun gate_activityRenewsTheWindow() {
        val (g, _, setClock) = gate(now = 1_000_000L, idle = 60_000L)
        g.arm()
        setClock(1_000_000L + 50_000)
        g.onActivity()
        setClock(1_000_000L + 100_000)
        assertTrue(g.isArmed()) // 上次活动在 50s 时，窗口续到 110s
        setClock(1_000_000L + 110_001)
        assertFalse(g.isArmed())
    }

    @Test
    fun gate_taskWindowNeverOutlivesServerExpiry() {
        val (g, _, setClock) = gate(now = 1_000_000L, idle = 60_000L)
        g.arm(taskId = "task-1", expiresAt = 1_030_000L)
        assertTrue(g.isArmed("task-1"))
        assertFalse(g.isArmed("task-2"))
        setClock(1_020_000L)
        g.onActivity("task-1")
        setClock(1_030_001L)
        assertFalse(g.isArmed("task-1"))
    }

    @Test
    fun gate_activityFromForeignTaskCannotRenew() {
        val (g, _, setClock) = gate(now = 1_000_000L, idle = 60_000L)
        g.arm(taskId = "task-1", expiresAt = 1_030_000L)
        setClock(1_020_000L)
        g.onActivity("task-2")
        setClock(1_030_001L)
        assertFalse(g.isArmed("task-1"))
    }
}
