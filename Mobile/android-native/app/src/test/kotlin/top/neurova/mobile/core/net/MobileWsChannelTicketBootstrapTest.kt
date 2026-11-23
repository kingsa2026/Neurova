package top.neurova.mobile.core.net

import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * 票据自举判据（批三模拟器验证发现的真断链）：connect_ticket 仅内存（§5.1b），
 * 进程重启后 DeviceBridgeService.startBridge 直连时 ticketProvider 必为空——
 * connect() 不得就此死在 FAILED（前台服务只 connect 一次，无重试来源），
 * 必须走与 4001 同一收敛点：先续签（refreshTicket）再握手。
 * - 票据为空 → 触发续签，续签成功后以新票据完成握手（Authorization: Bearer）；
 * - 续签被拒（设备已解除配对）→ 终态 FAILED + device_deregistered 事件，不发起握手。
 */
class MobileWsChannelTicketBootstrapTest {

    private lateinit var server: MockWebServer
    private lateinit var scope: CoroutineScope
    private lateinit var client: OkHttpClient
    private var spy: ServerSpy? = null

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        client = OkHttpClient.Builder().build()
    }

    @After
    fun tearDown() {
        scope.cancel()
        spy?.closeServerSide()
        client.connectionPool.evictAll()
        runCatching { server.shutdown() }
    }

    private inner class ServerSpy : okhttp3.WebSocketListener() {
        val received = LinkedBlockingQueue<String>()
        val connections = AtomicInteger(0)

        @Volatile
        private var serverSocket: okhttp3.WebSocket? = null

        override fun onOpen(webSocket: okhttp3.WebSocket, response: okhttp3.Response) {
            serverSocket = webSocket
            connections.incrementAndGet()
        }

        override fun onMessage(webSocket: okhttp3.WebSocket, text: String) {
            received.add(text)
        }

        fun closeServerSide() {
            serverSocket?.close(1000, "teardown")
        }
    }

    /** 票据仓替身：ticket 为空模拟进程重启后的内存态；refreshTicket 模拟续签回填 */
    private fun newChannelWithVolatileTicket(
        ticket: java.util.concurrent.atomic.AtomicReference<String?>,
        refreshTicket: suspend () -> String,
    ): MobileWsChannel {
        val url = server.url("/api/v1/mobile/ws").toString()
        return MobileWsChannel(
            scope = scope,
            wsUrlProvider = { url },
            ticketProvider = { ticket.get() },
            refreshTicket = refreshTicket,
            heartbeatIntervalMs = 60_000L,
            client = client,
        )
    }

    private fun awaitConnection(spy: ServerSpy, expectedCount: Int, timeoutMs: Long = 5000): Boolean {
        val deadline = System.nanoTime() + timeoutMs * 1_000_000
        while (System.nanoTime() < deadline) {
            if (spy.connections.get() >= expectedCount) return true
            Thread.sleep(50)
        }
        return false
    }

    @Test
    fun connectWithBlankTicketRefreshesThenHandshakes() {
        val spy = ServerSpy().also { spy = it }
        server.enqueue(MockResponse().withWebSocketUpgrade(spy))
        val ticket = java.util.concurrent.atomic.AtomicReference<String?>(null)
        val refreshCount = AtomicInteger(0)
        val channel = newChannelWithVolatileTicket(ticket) {
            refreshCount.incrementAndGet()
            "ticket-new".also { ticket.set(it) }
        }

        channel.connect()
        assertTrue("续签后应以新票据完成握手（连接数=1）", awaitConnection(spy, 1))

        val request = server.takeRequest(2, TimeUnit.SECONDS)
        assertNotNull("握手请求缺失", request)
        assertEquals(
            "握手必须携带续签后的新票据",
            "Bearer ticket-new",
            request!!.getHeader("Authorization"),
        )
        assertEquals("续签恰好触发一次", 1, refreshCount.get())
        channel.close()
    }

    @Test
    fun connectWithRevokedDeviceFailsWithDeregistered() {
        val spy = ServerSpy().also { spy = it }
        val ticket = java.util.concurrent.atomic.AtomicReference<String?>(null)
        val channel = newChannelWithVolatileTicket(ticket) {
            throw IllegalStateException("device_not_paired")
        }
        val errors = LinkedBlockingQueue<MobileWsChannel.Event.Error>()
        scope.launch { channel.events.collect { if (it is MobileWsChannel.Event.Error) errors.add(it) } }
        // 订阅先行：SharedFlow 无重放，collector 未就绪会漏掉快速上抛的事件
        Thread.sleep(300)

        channel.connect()
        Thread.sleep(800)

        assertEquals("续签被拒不得发起握手", 0, spy.connections.get())
        val event = errors.poll(2, TimeUnit.SECONDS)
        assertNotNull("续签被拒必须上抛 device_deregistered 事件", event)
        assertEquals("device_deregistered", event!!.code)
        assertEquals(MobileWsChannel.State.FAILED, channel.state.value)
    }

    @Test
    fun connectWithExistingTicketDoesNotRefresh() {
        val spy = ServerSpy().also { spy = it }
        server.enqueue(MockResponse().withWebSocketUpgrade(spy))
        val ticket = java.util.concurrent.atomic.AtomicReference<String?>("ticket-warm")
        var refreshCalled = false
        val channel = newChannelWithVolatileTicket(ticket) {
            refreshCalled = true
            "ticket-should-not-happen"
        }

        channel.connect()
        assertTrue(awaitConnection(spy, 1))
        Thread.sleep(300)
        assertEquals("票据在场时不得触发续签", false, refreshCalled)
        val request = server.takeRequest(2, TimeUnit.SECONDS)
        assertEquals("Bearer ticket-warm", request!!.getHeader("Authorization"))
        channel.close()
    }

    @Test
    fun connectWhileAlreadyConnectedDoesNotDuplicateSocket() {
        val spy = ServerSpy().also { spy = it }
        server.enqueue(MockResponse().withWebSocketUpgrade(spy))
        server.enqueue(MockResponse().withWebSocketUpgrade(spy))
        val ticket = java.util.concurrent.atomic.AtomicReference<String?>("ticket-a")
        val channel = newChannelWithVolatileTicket(ticket) { "ticket-b".also { ticket.set(it) } }

        channel.connect()
        assertTrue(awaitConnection(spy, 1))
        // 已连接态再次 connect（如配对就绪信号重复触发）不得开出第二条 socket
        channel.connect()
        Thread.sleep(600)
        assertEquals("已连接时重复 connect 不得新建连接", 1, spy.connections.get())
        channel.close()
    }

    @Test
    fun connectIfIdleOnlyFiresFromRestingStates() {
        val spy = ServerSpy().also { spy = it }
        server.enqueue(MockResponse().withWebSocketUpgrade(spy))
        val ticket = java.util.concurrent.atomic.AtomicReference<String?>("ticket-a")
        val url = java.util.concurrent.atomic.AtomicReference<String?>(null)
        val channel = MobileWsChannel(
            scope = scope,
            wsUrlProvider = { url.get() },
            ticketProvider = { ticket.get() },
            refreshTicket = { "ticket-b".also { ticket.set(it) } },
            heartbeatIntervalMs = 60_000L,
            client = client,
        )

        // IDLE 发起但无地址 → FAILED（静止态）
        assertEquals(true, channel.connectIfIdle())
        assertEquals(MobileWsChannel.State.FAILED, channel.state.value)
        // FAILED 仍是静止态：幂等入口可再次发起（仍无地址 → 维持 FAILED）
        assertEquals(true, channel.connectIfIdle())
        // 地址就绪后从 FAILED 发起 → 真握手
        url.set(server.url("/api/v1/mobile/ws").toString())
        assertEquals(true, channel.connectIfIdle())
        assertTrue(awaitConnection(spy, 1))
        // 已连接：幂等入口不动作
        assertEquals(false, channel.connectIfIdle())
        Thread.sleep(300)
        assertEquals(1, spy.connections.get())
        channel.close()
    }
}
