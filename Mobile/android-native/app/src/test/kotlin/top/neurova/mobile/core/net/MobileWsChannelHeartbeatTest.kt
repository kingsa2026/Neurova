package top.neurova.mobile.core.net

import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import okhttp3.OkHttpClient
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * 安卓 WS 心跳契约测试（审计 P0-2）：客户端心跳帧必须与后端
 * `neurova/api/endpoints/mobile_pairing.py` 消息循环同契约——
 * 后端 `json.loads` 只吃 JSON，裸文本 "ping" 会炸掉连接；pong 是
 * JSON 帧 `{"type":"pong",...}`，客户端必须按 type 识别并据此判定超时。
 * 鸿蒙端 WebSocketAdapter 的 `{"type":"ping"}` 是契约基准，两端不得再分叉。
 */
class MobileWsChannelHeartbeatTest {

    private lateinit var server: MockWebServer
    private lateinit var scope: CoroutineScope
    private lateinit var client: OkHttpClient

    /** 各测试装入自己的 spy，tearDown 统一收口 */
    private var spy: ServerSpy? = null

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        client = OkHttpClient.Builder().callTimeout(3, TimeUnit.SECONDS).build()
    }

    @After
    fun tearDown() {
        scope.cancel()
        // 先从服务端侧收口 socket，再清连接池；MockWebServer 对 websocket 升级连接的
        // shutdown 有「Gave up waiting for queue to shut down」的已知噪音（裸 OkHttp
        // 客户端干净 close 后同样复现，与被测码无关），断言均在测试体内不受掩盖
        spy?.closeServerSide()
        client.connectionPool.evictAll()
        runCatching { server.shutdown() }
    }

    /** 服务端替身：记录收到的帧与 close 码；onReply 可选回应答帧 */
    private class ServerSpy(
        private val onReply: (WebSocket, String) -> Unit = { _, _ -> },
    ) : WebSocketListener() {
        val received = LinkedBlockingQueue<String>()
        val closeCodes = LinkedBlockingQueue<Int>()

        @Volatile
        private var serverSocket: WebSocket? = null

        override fun onOpen(webSocket: WebSocket, response: okhttp3.Response) {
            serverSocket = webSocket
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            received.add(text)
            onReply(webSocket, text)
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            closeCodes.add(code)
        }

        fun closeServerSide() {
            serverSocket?.close(1000, "teardown")
        }
    }

    private fun newChannel(spy: ServerSpy, heartbeatMs: Long, pongTimeoutMs: Long): MobileWsChannel {
        this.spy = spy
        val url = server.url("/api/v1/mobile/ws").toString()
        return MobileWsChannel(
            scope = scope,
            wsUrlProvider = { url },
            ticketProvider = { "ticket-test" },
            refreshTicket = { "" },
            heartbeatIntervalMs = heartbeatMs,
            pongTimeoutMs = pongTimeoutMs,
            client = client,
        )
    }

    @Test
    fun heartbeatFrameIsJsonPingNotBareText() {
        val spy = ServerSpy()
        server.enqueue(MockResponse().withWebSocketUpgrade(spy))
        val channel = newChannel(spy, heartbeatMs = 100, pongTimeoutMs = 500)
        channel.connect()

        val frame = spy.received.poll(3, TimeUnit.SECONDS)
        assertNotNull("心跳周期内服务端未收到任何帧", frame)
        val parsed = runCatching { Json.parseToJsonElement(frame) as? JsonObject }.getOrNull()
        assertNotNull("心跳帧不是合法 JSON：$frame（后端 json.loads 会拆连接）", parsed)
        assertEquals("ping", parsed?.get("type")?.toString()?.trim('"'))
        channel.close()
    }

    @Test
    fun connectionSurvivesHeartbeatCycleWhenPongArrives() {
        val spy = ServerSpy { ws, text ->
            if (text.contains("ping")) ws.send("{\"type\":\"pong\",\"timestamp\":1.0}")
        }
        server.enqueue(MockResponse().withWebSocketUpgrade(spy))
        val channel = newChannel(spy, heartbeatMs = 100, pongTimeoutMs = 500)
        channel.connect()

        // 跑满两个心跳周期：pong 正常往返时连接必须保持，不得被无条件拆线
        Thread.sleep(1300)
        assertEquals(MobileWsChannel.State.AUTHED, channel.state.value)
        assertTrue("收到 pong 后不得拆线，实际 close 码：${spy.closeCodes}", spy.closeCodes.isEmpty())
        channel.close()
    }

    @Test
    fun silentPongStillTimesOutAndCloses() {
        val spy = ServerSpy() // 从不应答 pong
        server.enqueue(MockResponse().withWebSocketUpgrade(spy))
        val channel = newChannel(spy, heartbeatMs = 100, pongTimeoutMs = 500)
        channel.connect()

        val code = spy.closeCodes.poll(3, TimeUnit.SECONDS)
        assertEquals(
            "pong 超时必须主动拆线走重连档（1006 是 RFC 保留码，线上合法码用 1000）",
            1000,
            code?.toInt(),
        )
        channel.close()
    }
}
