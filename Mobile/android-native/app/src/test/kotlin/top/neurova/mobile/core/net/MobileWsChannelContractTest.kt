package top.neurova.mobile.core.net

import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * D-5 三端契约对齐（安卓侧）：服务端 pong 帧 `connection_runtime` 字段
 * （G4 describeForClients 单源）到达后，心跳周期与重连退避取值必须跟随
 * 契约，不再手抄。旧后端（pong 无该字段）行为零变化。
 */
class MobileWsChannelContractTest {

    private lateinit var server: MockWebServer
    private lateinit var scope: CoroutineScope
    private lateinit var client: OkHttpClient
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
        spy?.closeServerSide()
        client.connectionPool.evictAll()
        runCatching { server.shutdown() }
    }

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

    private fun newChannel(spy: ServerSpy, heartbeatMs: Long): MobileWsChannel {
        this.spy = spy
        val url = server.url("/api/v1/mobile/ws").toString()
        return MobileWsChannel(
            scope = scope,
            wsUrlProvider = { url },
            ticketProvider = { "ticket-test" },
            refreshTicket = { "" },
            heartbeatIntervalMs = heartbeatMs,
            client = client,
        )
    }

    @Test
    fun pongContractUpdatesHeartbeatInterval() {
        // 服务端对每个 ping 回带契约 pong：心跳 0.1s、退避 base 0.5s / cap 30s
        val spy = ServerSpy { ws, text ->
            if (text.contains("ping")) {
                ws.send(
                    "{\"type\":\"pong\",\"timestamp\":1.0,\"connection_runtime\":{" +
                        "\"version\":1," +
                        "\"heartbeat\":{\"interval_s\":0.1}," +
                        "\"reconnect\":{\"backoff_base_s\":0.5,\"backoff_cap_s\":30.0}}}",
                )
            }
        }
        server.enqueue(MockResponse().withWebSocketUpgrade(spy))
        val channel = newChannel(spy, heartbeatMs = 1_000)
        channel.connect()

        // 3s 采样窗：若契约被消费，周期从 1s 加速到 0.1s，应收到 ≥6 帧；
        // 不消费契约则维持 1s 周期，3s 仅 ~3 帧（= 红灯）。
        var count = 0
        val deadline = System.nanoTime() + 3_000_000_000L
        while (System.nanoTime() < deadline) {
            if (spy.received.poll(50, TimeUnit.MILLISECONDS) != null) count++
        }
        channel.close()
        assertTrue("契约到达后心跳应加速到 100ms（3s 内 ≥6 帧），实际 $count", count >= 6)
    }

    @Test
    fun backoffDelayMsFollowsServerContract() {
        // 契约形态：base 0.5s / cap 30s
        assertEquals(1_000L, MobileWsChannel.backoffDelayMs(1, 500, 30_000))
        assertEquals(30_000L, MobileWsChannel.backoffDelayMs(6, 500, 30_000))
        // 缺省回归：旧常量（1s/16s）行为不变
        assertEquals(2_000L, MobileWsChannel.backoffDelayMs(1, 1_000, 16_000))
        assertEquals(16_000L, MobileWsChannel.backoffDelayMs(4, 1_000, 16_000))
    }
}
