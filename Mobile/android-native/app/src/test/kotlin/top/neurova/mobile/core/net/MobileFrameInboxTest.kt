package top.neurova.mobile.core.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MobileFrameInboxTest {
    @Test
    fun queueSurvivesRestartAndAckIsBatchedByCaller() {
        var stored = ""
        val first = MobileFrameInbox(load = { stored }, save = { stored = it })
        assertTrue(first.enqueue("""{"seq":1}"""))
        assertTrue(first.enqueue("""{"seq":2}"""))
        val restored = MobileFrameInbox(load = { stored }, save = { stored = it })
        assertEquals("""{"seq":1}""", restored.peek())
        restored.ack()
        assertEquals("""{"seq":2}""", restored.peek())
        restored.ack()
        assertNull(restored.peek())
    }

    @Test
    fun overflowIsRejectedRatherThanSilentlyDroppingNewestFrame() {
        val inbox = MobileFrameInbox(capacity = 2, load = { "" }, save = {})
        assertTrue(inbox.enqueue("a"))
        assertTrue(inbox.enqueue("b"))
        assertFalse(inbox.enqueue("c"))
        assertEquals("a", inbox.peek())
    }
}
