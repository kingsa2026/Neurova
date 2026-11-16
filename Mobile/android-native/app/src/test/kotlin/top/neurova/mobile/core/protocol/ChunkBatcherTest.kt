package top.neurova.mobile.core.protocol

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 流式分块批处理器（M5.2.1 同源语义，鸿蒙 ChunkBatcher 移植）：
 * chat:chunk 每 token 一次直达 UI 会造成渲染风暴，按 60ms 时间窗批量追加。
 */
class ChunkBatcherTest {

    @Test
    fun pushesAccumulateInOrder() {
        val batcher = ChunkBatcher()
        batcher.push("你好")
        batcher.push("，")
        batcher.push("世界")
        assertEquals("你好，世界", batcher.forceFlush())
    }

    @Test
    fun flushReturnsAccumulatedAndEmptiesBuffer() {
        val batcher = ChunkBatcher()
        batcher.push("abc")
        batcher.push("def")
        val out = batcher.flush(nowMs = 1000)
        assertEquals("abcdef", out)
        assertEquals("", batcher.forceFlush())
    }

    @Test
    fun shouldFlushRespectsTimeWindow() {
        val batcher = ChunkBatcher(windowMs = 60)
        batcher.push("x")
        assertFalse("窗口内不应触发", batcher.shouldFlush(nowMs = 0))
        assertTrue("窗口过后应触发", batcher.shouldFlush(nowMs = 61))
    }

    @Test
    fun shouldFlushFalseWhenBufferEmpty() {
        val batcher = ChunkBatcher()
        assertFalse(batcher.shouldFlush(nowMs = 100_000))
    }

    @Test
    fun flushRecordsWindowAnchor() {
        val batcher = ChunkBatcher(windowMs = 60)
        batcher.push("a")
        assertTrue(batcher.shouldFlush(nowMs = 100))
        batcher.flush(nowMs = 100)
        batcher.push("b")
        assertFalse("刚 flush 过，窗口内不再触发", batcher.shouldFlush(nowMs = 120))
        assertTrue(batcher.shouldFlush(nowMs = 161))
    }

    @Test
    fun forceFlushDoesNotTouchWindowAnchor() {
        val batcher = ChunkBatcher(windowMs = 60)
        batcher.push("a")
        batcher.flush(nowMs = 100)
        batcher.push("b")
        assertEquals("b", batcher.forceFlush())
        batcher.push("c")
        assertTrue("forceFlush 不推进锚点，窗口判定不受影响", batcher.shouldFlush(nowMs = 161))
    }

    @Test
    fun resetClearsEverything() {
        val batcher = ChunkBatcher()
        batcher.push("abc")
        batcher.flush(nowMs = 10)
        batcher.push("def")
        batcher.reset()
        assertEquals("", batcher.forceFlush())
        assertFalse(batcher.shouldFlush(nowMs = 100_000))
    }
}
