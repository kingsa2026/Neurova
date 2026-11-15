package top.neurova.mobile.core.protocol

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * SSE 分帧解析契约（对齐 neurova/api/endpoints/chat.py 事件流）：
 * event:/data: 成对，空行分帧，": ping" 注释心跳忽略，CRLF/LF 均容。
 * 红灯：SseFrameParser 尚未实现（桩恒返空表）。
 */
class SseFrameParserTest {

    @Test
    fun startMessageDoneFramesParseWithNamedEvents() {
        val wire = "event: start\ndata: {\"request_id\":\"r1\",\"session_id\":\"s1\"}\n\n" +
            "event: message\ndata: {\"content\":\"你好\"}\n\n" +
            "event: done\ndata: {\"request_id\":\"r1\"}\n\n"
        val frames = SseFrameParser.parse(wire)
        assertEquals(3, frames.size)
        assertEquals("start", frames[0].event)
        assertEquals("{\"request_id\":\"r1\",\"session_id\":\"s1\"}", frames[0].data)
        assertEquals("message", frames[1].event)
        assertEquals("done", frames[2].event)
    }

    @Test
    fun pingCommentHeartbeatLinesAreDropped() {
        val wire = ": ping\n\n" +
            "event: message\ndata: {\"content\":\"a\"}\n\n" +
            ": ping\n\n"
        val frames = SseFrameParser.parse(wire)
        assertEquals(1, frames.size)
        assertEquals("message", frames[0].event)
    }

    @Test
    fun crlfLineEndingsAreAccepted() {
        val wire = "event: message\r\ndata: {\"content\":\"x\"}\r\n\r\n"
        val frames = SseFrameParser.parse(wire)
        assertEquals(1, frames.size)
        assertEquals("{\"content\":\"x\"}", frames[0].data)
    }

    @Test
    fun multilineDataIsJoinedWithNewline() {
        val frames = SseFrameParser.parse("event: message\ndata: line-one\ndata: line-two\n\n")
        assertEquals(1, frames.size)
        assertEquals("line-one\nline-two", frames[0].data)
    }

    @Test
    fun truncatedTailWithoutBlankLineIsNotEmitted() {
        val wire = "event: message\ndata: {\"content\":\"ok\"}\n\n" +
            "event: message\ndata: {\"content\":\"par"
        val frames = SseFrameParser.parse(wire)
        assertEquals(1, frames.size)
    }

    @Test
    fun defaultEventIsMessageWhenOnlyDataLines() {
        val frames = SseFrameParser.parse("data: bare\n\n")
        assertEquals(1, frames.size)
        assertTrue(frames[0].event.isEmpty() || frames[0].event == "message")
    }
}
