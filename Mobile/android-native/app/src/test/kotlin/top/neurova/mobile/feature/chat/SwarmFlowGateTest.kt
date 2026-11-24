package top.neurova.mobile.feature.chat

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 协作拓扑入口门单测（对齐鸿蒙端 SwarmFlowGate 同名判定）：
 * 无协作不显示；有协作默认浮动图标；展开后面板接管入口。
 */
class SwarmFlowGateTest {
    @Test
    fun `no runs and no cards means no collab`() {
        assertFalse(swarmHasCollab(0, 0))
    }

    @Test
    fun `one run counts as collab`() {
        assertTrue(swarmHasCollab(1, 0))
    }

    @Test
    fun `multiple runs count as collab`() {
        assertTrue(swarmHasCollab(3, 0))
    }

    @Test
    fun `approval or candidate cards alone count as collab`() {
        assertTrue(swarmHasCollab(0, 2))
    }

    @Test
    fun `collab and collapsed shows floating icon`() {
        assertTrue(showSwarmFloatingIcon(hasCollab = true, expanded = false))
    }

    @Test
    fun `collab and expanded hides floating icon`() {
        assertFalse(showSwarmFloatingIcon(hasCollab = true, expanded = true))
    }

    @Test
    fun `no collab never shows floating icon`() {
        assertFalse(showSwarmFloatingIcon(hasCollab = false, expanded = false))
        assertFalse(showSwarmFloatingIcon(hasCollab = false, expanded = true))
    }
}
