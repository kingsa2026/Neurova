package top.neurova.mobile.core.net

import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
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

/** P2-23：JSON、去重、游标批量推进与 scope 即时订阅的生产通道判据。 */
class MobileWsChannelReliabilityTest {
    private lateinit var server: MockWebServer
    private lateinit var scope: CoroutineScope
    private lateinit var client: OkHttpClient
    private val received = LinkedBlockingQueue<String>()
    private val connections = AtomicInteger()

    @Volatile
    private var serverSocket: WebSocket? = null

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        client = OkHttpClient.Builder().callTimeout(10, TimeUnit.SECONDS).build()
    }

    @After
    fun tearDown() {
        scope.cancel()
        serverSocket?.close(1000, "teardown")
        client.connectionPool.evictAll()
        runCatching { server.shutdown() }
    }

    private fun enqueueUpgrade() {
        val listener = object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: okhttp3.Response) {
                serverSocket = webSocket
                connections.incrementAndGet()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                received.add(text)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(code, reason)
            }
        }
        server.enqueue(MockResponse().withWebSocketUpgrade(listener))
    }

    private fun channel(persist: (Int) -> Unit = {}): MobileWsChannel {
        enqueueUpgrade()
        val url = server.url("/api/v1/mobile/ws").toString()
        return MobileWsChannel(
            scope = scope,
            wsUrlProvider = { url },
            ticketProvider = { "ticket-test" },
            refreshTicket = { "" },
            heartbeatIntervalMs = 60_000,
            lastSeqPersist = persist,
            client = client,
        )
    }

    private fun await(predicate: () -> Boolean) {
        val deadline = System.nanoTime() + 3_000_000_000L
        while (System.nanoTime() < deadline) {
            if (predicate()) return
            Thread.sleep(20)
        }
        error("条件未满足；received=${received.toList()}")
    }

    @Test
    fun jsonEscapesRemainExactAndMessageIdsDeduplicate() {
        val channel = channel()
        val events = mutableListOf<MobileWsChannel.Event>()
        scope.launch { channel.events.collect { events.add(it) } }
        channel.connect()
        await { connections.get() == 1 }
        val content = "引号\" 反斜杠\\ 换行\n 中文"
        val encoder = kotlinx.serialization.json.Json
        val body = encoder.encodeToString(
            kotlinx.serialization.json.JsonObject.serializer(),
            kotlinx.serialization.json.JsonObject(mapOf(
                "type" to kotlinx.serialization.json.JsonPrimitive("chat:chunk"),
                "session_id" to kotlinx.serialization.json.JsonPrimitive("s\"1"),
                "message_id" to kotlinx.serialization.json.JsonPrimitive("m-1"),
                "content" to kotlinx.serialization.json.JsonPrimitive(content),
                "seq" to kotlinx.serialization.json.JsonPrimitive(7),
            )),
        )
        serverSocket!!.send(body)
        serverSocket!!.send(body)
        await { events.any { it is MobileWsChannel.Event.Chunk } }
        Thread.sleep(100)
        val chunks = events.filterIsInstance<MobileWsChannel.Event.Chunk>()
        assertEquals(1, chunks.size)
        assertEquals(content, chunks.single().content)
        assertEquals("s\"1", chunks.single().sessionId)
        channel.close()
    }

    @Test
    fun duplicateBusinessIdStillAdvancesCursorToMaximum() {
        val persisted = mutableListOf<Int>()
        val channel = channel { persisted.add(it) }
        val events = mutableListOf<MobileWsChannel.Event>()
        scope.launch { channel.events.collect { events.add(it) } }
        channel.connect()
        await { connections.get() == 1 }
        serverSocket!!.send("""{"type":"chat:chunk","session_id":"s","message_id":"m-1","content":"a","seq":11}""")
        serverSocket!!.send("""{"type":"chat:chunk","session_id":"s","message_id":"m-1","content":"a","seq":12}""")
        await { persisted.contains(12) }
        assertEquals(1, events.filterIsInstance<MobileWsChannel.Event.Chunk>().size)
        channel.close()
    }

    @Test
    fun cursorTakesMaximumAndPersistsOneBatchAfterConsumption() {
        val persisted = mutableListOf<Int>()
        val channel = channel { persisted.add(it) }
        channel.connect()
        await { connections.get() == 1 }
        serverSocket!!.send("""{"type":"chat:done","session_id":"s","seq":9}""")
        serverSocket!!.send("""{"type":"chat:done","session_id":"s","seq":4}""")
        await { persisted.isNotEmpty() }
        Thread.sleep(150)
        assertEquals(listOf(9), persisted)
        channel.close()
    }

    @Test
    fun scopeChangeNotifiesServerImmediatelyAndReconnectResubscribes() {
        val channel = channel()
        channel.connect()
        await { connections.get() == 1 }
        channel.setSubscriptionScope("session", "s-1")
        await { received.any { it.contains("sync_scope") } }
        val notice = received.first { it.contains("sync_scope") }
        assertTrue(notice.contains("\"scope\":\"session\""))
        assertTrue(notice.contains("\"scope_key\":\"s-1\""))
        channel.close()
    }

    @Test
    fun reconnectResendsSelectedSubscriptionScope() {
        val channel = channel()
        enqueueUpgrade()
        channel.connect()
        await { connections.get() == 1 }
        channel.setSubscriptionScope("session", "s-reconnect")
        await { received.any { it.contains("sync_scope") && it.contains("s-reconnect") } }
        serverSocket!!.close(1000, "force-reconnect")
        await { connections.get() == 2 }
        await {
            received.count {
                it.contains("sync_scope") && it.contains("s-reconnect")
            } >= 2
        }
        channel.close()
    }

    @Test
    fun staleConnectionCallbacksAreIgnoredAfterNewGeneration() {
        val channel = channel()
        channel.connect()
        await { connections.get() == 1 && channel.state.value == MobileWsChannel.State.AUTHED }
        val field = MobileWsChannel::class.java.getDeclaredField("socket")
        field.isAccessible = true
        val currentSocket = field.get(channel) as WebSocket
        assertTrue(channel.isCurrentConnection(currentSocket, 1))
        assertTrue(!channel.isCurrentConnection(currentSocket, 0))
        channel.close()
    }

    @Test
    fun errorCarriesSessionIdForIsolatedRouting() {
        val channel = channel()
        val events = mutableListOf<MobileWsChannel.Event>()
        scope.launch { channel.events.collect { events.add(it) } }
        channel.connect()
        await { connections.get() == 1 }
        serverSocket!!.send("""{"type":"error","code":"chat_failed","message":"boom","session_id":"s-err","seq":2}""")
        await { events.any { it is MobileWsChannel.Event.Error } }
        val event = events.filterIsInstance<MobileWsChannel.Event.Error>().single()
        val sessionId = event.javaClass.methods.firstOrNull { it.name == "getSessionId" }?.invoke(event)
        assertEquals("s-err", sessionId)
        channel.close()
    }
}
