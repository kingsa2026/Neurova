package top.neurova.mobile.core.protocol

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import top.neurova.mobile.core.net.MobileWsChannel

/**
 * WS 握手契约（2026-11-16 实机实证）：接入凭证走 **Authorization: Bearer** 头
 * （鸿蒙 WebSocketAdapter 同款、后端 _ticketFromHandshake 的优先通道）。
 * 子协议 `neurova.auth.<ticket>` 形态不可用——ticket 含冒号，不是合法的
 * RFC6455 子协议 token，OkHttp/uvicorn 侧握手直接失败（wsprobe 实测复现）。
 */
class WsHandshakeRequestTest {

    @Test
    fun handshakeCarriesBearerTicketHeader() {
        val request = MobileWsChannel.buildHandshakeRequest("ws://10.0.2.2:9527/api/v1/mobile/ws", "ticket-1")
        assertEquals("Bearer ticket-1", request.header("Authorization"))
    }

    @Test
    fun handshakeDoesNotUseSubprotocol() {
        val request = MobileWsChannel.buildHandshakeRequest("ws://10.0.2.2:9527/api/v1/mobile/ws", "ticket-1")
        assertNull("子协议形态已证伪，不得回潮", request.header("Sec-WebSocket-Protocol"))
    }

    @Test
    fun handshakeTargetsGivenUrl() {
        val request = MobileWsChannel.buildHandshakeRequest("ws://10.0.2.2:9527/api/v1/mobile/ws", "t")
        // OkHttp 把 ws:// 规范化为 http://（同一 HttpUrl 通道），host/路径保持一致
        assertEquals("http://10.0.2.2:9527/api/v1/mobile/ws", request.url.toString())
    }
}
