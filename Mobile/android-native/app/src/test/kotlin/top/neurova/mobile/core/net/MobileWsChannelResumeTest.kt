package top.neurova.mobile.core.net

import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
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
 * D3 客户端语义（安卓侧补齐）：出站帧游标 + 断线重连 sync_resume 补拉 +
 * scope 按需订阅 + sync_snapshot_required 快照降级。对齐鸿蒙
 * WebSocketAdapter 与服务端 mobile_pairing/mobile_ws_ledger 契约：
 * - 服务端出站帧先落账再发送（带单调 seq）；
 * - 重连成功且游标 > 0 时发 sync_resume{last_seq, scope?, scope_key?}，
 *   服务端补发 (cursor, head] 的帧（带 replay 标记）；
 * - 游标过旧/非法 → 服务端回 sync_snapshot_required，客户端弃游标拆线
 *   重连（首连语义走历史快照恢复）；
 * - scope 缺省 global 不带参数；session/thread 必带 scope_key。
 */
class MobileWsChannelResumeTest {

    private lateinit var server: MockWebServer
    private lateinit var scope: CoroutineScope
    private lateinit var client: OkHttpClient
    private var spy: ServerSpy? = null

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        client = OkHttpClient.Builder().callTimeout(30, TimeUnit.SECONDS).build()
    }

    @After
    fun tearDown() {
        scope.cancel()
        spy?.closeServerSide()
        client.connectionPool.evictAll()
        runCatching { server.shutdown() }
    }

    /** 服务端替身：received=服务端收到的帧（client→server）；sentToClient=服务端发出的帧 */
    private inner class ServerSpy : WebSocketListener() {
        val received = LinkedBlockingQueue<String>()
        val sentToClient = LinkedBlockingQueue<String>()
        val closeCodes = LinkedBlockingQueue<Int>()
        val connections = AtomicInteger(0)

        @Volatile
        private var serverSocket: WebSocket? = null

        override fun onOpen(webSocket: WebSocket, response: okhttp3.Response) {
            serverSocket = webSocket
            connections.incrementAndGet()
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            received.add(text)
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            closeCodes.add(code)
            // 真实服务端会完成关闭握手（回 close 帧）；OkHttp 不会代答——
            // 不回应则 client 的 onClosed 永不触发，重连链路挂起
            webSocket.close(code, reason)
        }

        fun sendToServer(text: String) {
            sentToClient.add(text)
            serverSocket?.send(text)
        }

        fun closeServerSide() {
            serverSocket?.close(1000, "teardown")
        }
    }

    private fun newChannel(): MobileWsChannel {
        val url = server.url("/api/v1/mobile/ws").toString()
        return MobileWsChannel(
            scope = scope,
            wsUrlProvider = { url },
            ticketProvider = { "ticket-test" },
            refreshTicket = { "" },
            heartbeatIntervalMs = 60_000L, // 心跳不打扰帧序断言
            client = client,
        )
    }

    /** 轮询取回满足条件的帧（找不到返回 null） */
    private fun awaitFrame(spy: ServerSpy, timeoutMs: Long, predicate: (String) -> Boolean): String? {
        val deadline = System.nanoTime() + timeoutMs * 1_000_000
        while (System.nanoTime() < deadline) {
            val frame = spy.received.poll(50, TimeUnit.MILLISECONDS)
            if (frame != null && predicate(frame)) return frame
        }
        return null
    }

    /** 轮询等待服务端向客户端发出的帧（找不到返回 null） */
    private fun awaitSent(spy: ServerSpy, timeoutMs: Long, predicate: (String) -> Boolean): String? {
        val deadline = System.nanoTime() + timeoutMs * 1_000_000
        while (System.nanoTime() < deadline) {
            val frame = spy.sentToClient.poll(50, TimeUnit.MILLISECONDS)
            if (frame != null && predicate(frame)) return frame
        }
        return null
    }

    private fun awaitConnection(
        spy: ServerSpy,
        expectedCount: Int,
        timeoutMs: Long = 5000,
        channel: MobileWsChannel? = null,
    ): Boolean {
        val deadline = System.nanoTime() + timeoutMs * 1_000_000
        while (System.nanoTime() < deadline) {
            if (spy.connections.get() >= expectedCount) return true
            Thread.sleep(50)
        }
        val state = channel?.state?.value
        throw AssertionError(
            "连接数未达 $expectedCount：conns=${spy.connections.get()} " +
                "closes=${spy.closeCodes} state=$state received=${spy.received.toList()} " +
                "sent=${spy.sentToClient.toList()}",
        )
    }

    private fun parse(raw: String): JsonObject =
        Json.parseToJsonElement(raw) as JsonObject

    @Test
    fun reconnectResumesWithCursorAndScope() {
        val spy = ServerSpy().also { spy = it }
        // 两条连接额度：首连 → 断开 → 重连（同一 spy 跨连接累积记录）
        server.enqueue(MockResponse().withWebSocketUpgrade(spy))
        server.enqueue(MockResponse().withWebSocketUpgrade(spy))
        val channel = newChannel()
        channel.setSubscriptionScope("session", "s-1")
        channel.connect()
        assertTrue(awaitConnection(spy, 1, channel = channel))

        // 首连收到带 seq 的业务帧：游标推进到 5
        spy.sendToServer("""{"type":"chat:done","session_id":"s-1","seq":5}""")
        awaitSent(spy, 2000) { it.contains("chat:done") }

        // 服务端拆线 → 客户端按 1000 语义重连；重连后必须发 sync_resume 补拉
        spy.closeServerSide()
        assertTrue(awaitConnection(spy, 2, channel = channel))
        val resume = awaitFrame(spy, 5000) { it.contains("sync_resume") }
        assertNotNull("重连后未发 sync_resume 补拉", resume)
        val parsed = parse(resume!!)
        assertEquals("sync_resume", parsed["type"]?.toString()?.trim('"'))
        assertEquals(5, parsed["last_seq"]?.toString()?.trim('"')?.toIntOrNull())
        assertEquals("session", parsed["scope"]?.toString()?.trim('"'))
        assertEquals("s-1", parsed["scope_key"]?.toString()?.trim('"'))
        channel.close()
    }

    @Test
    fun firstConnectDoesNotResume() {
        val spy = ServerSpy().also { spy = it }
        // 两条连接额度：首连 → 断开 → 重连（同一 spy 跨连接累积记录）
        server.enqueue(MockResponse().withWebSocketUpgrade(spy))
        server.enqueue(MockResponse().withWebSocketUpgrade(spy))
        val channel = newChannel()
        channel.setSubscriptionScope("session", "s-1")
        channel.connect()
        assertTrue(awaitConnection(spy, 1, channel = channel))
        // 首连游标为 0：不得发 sync_resume（避免注入额外首帧）
        val stray = awaitFrame(spy, 1200) { it.contains("sync_resume") }
        assertEquals("首连不应发 sync_resume", null, stray)
        channel.close()
    }

    @Test
    fun snapshotRequiredDropsCursorAndReconnects() {
        val spy = ServerSpy().also { spy = it }
        // 两条连接额度：首连 → 断开 → 重连（同一 spy 跨连接累积记录）
        server.enqueue(MockResponse().withWebSocketUpgrade(spy))
        server.enqueue(MockResponse().withWebSocketUpgrade(spy))
        val channel = newChannel()
        channel.connect() // global 缺省
        assertTrue(awaitConnection(spy, 1, channel = channel))
        spy.sendToServer("""{"type":"chat:done","session_id":"s-1","seq":5}""")
        awaitSent(spy, 2000) { it.contains("chat:done") }

        // 游标过旧：服务端要求弃游标按快照重同步 → 客户端归零并拆线重连
        spy.sendToServer("""{"type":"sync_snapshot_required","reason":"cursor_pruned"}""")
        assertTrue(awaitConnection(spy, 2, timeoutMs = 8000, channel = channel))
        // 重连后游标已归零：不得携带旧游标补拉（首连语义，快照由历史链路恢复）
        val stray = awaitFrame(spy, 1500) { it.contains("sync_resume") }
        assertEquals("快照降级后不得再带旧游标补拉", null, stray)
        channel.close()
    }

    @Test
    fun invalidScopeKeepsPreviousScope() {
        val spy = ServerSpy().also { spy = it }
        // 两条连接额度：首连 → 断开 → 重连（同一 spy 跨连接累积记录）
        server.enqueue(MockResponse().withWebSocketUpgrade(spy))
        server.enqueue(MockResponse().withWebSocketUpgrade(spy))
        val channel = newChannel()
        channel.setSubscriptionScope("session", "s-1")
        channel.setSubscriptionScope("bogus", "x") // 非法：保持 session/s-1
        channel.connect()
        assertTrue(awaitConnection(spy, 1, channel = channel))
        spy.sendToServer("""{"type":"chat:done","session_id":"s-1","seq":3}""")
        awaitSent(spy, 2000) { it.contains("chat:done") }
        spy.closeServerSide()
        assertTrue(awaitConnection(spy, 2, channel = channel))
        val resume = awaitFrame(spy, 5000) { it.contains("sync_resume") }
        assertNotNull(resume)
        val parsed = parse(resume!!)
        assertEquals("session", parsed["scope"]?.toString()?.trim('"'))
        assertEquals("s-1", parsed["scope_key"]?.toString()?.trim('"'))
        channel.close()
    }
}
