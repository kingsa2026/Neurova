package top.neurova.mobile.core.net

import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import top.neurova.mobile.core.protocol.TunnelTokenSigner

/**
 * U9/U16 relay 鉴权新形态（卡 C 安卓侧）：
 * - relay 模式（`/t/<routeId>` 入口）连接后**首条**消息必须是 `auth` 帧，
 *   token 为本地签发的 `nv1:agent` 信封（裸密钥不上线），先于 sync_resume/心跳；
 * - 直连模式不发 auth 帧（首帧仍是心跳 ping），行为零变化。
 */
class MobileWsChannelRelayAuthTest {

    private lateinit var server: MockWebServer
    private lateinit var scope: CoroutineScope
    private lateinit var client: OkHttpClient
    private var spy: ServerSpy? = null

    private val relaySecret = "nv-relay-secret-1"

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        client = OkHttpClient.Builder().callTimeout(5, TimeUnit.SECONDS).build()
    }

    @After
    fun tearDown() {
        scope.cancel()
        spy?.closeServerSide()
        client.connectionPool.evictAll()
        runCatching { server.shutdown() }
    }

    private class ServerSpy : WebSocketListener() {
        val received = LinkedBlockingQueue<String>()

        @Volatile
        private var serverSocket: WebSocket? = null

        override fun onOpen(webSocket: WebSocket, response: okhttp3.Response) {
            serverSocket = webSocket
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            received.add(text)
        }

        fun closeServerSide() {
            serverSocket?.close(1000, "teardown")
        }
    }

    private fun newChannel(url: String, secretProvider: () -> String?, heartbeatMs: Long = 60_000L): MobileWsChannel {
        val spy = ServerSpy()
        this.spy = spy
        server.enqueue(MockResponse().withWebSocketUpgrade(spy))
        return MobileWsChannel(
            scope = scope,
            wsUrlProvider = { url },
            ticketProvider = { "ticket-test" },
            refreshTicket = { "" },
            relayAuthSecretProvider = secretProvider,
            heartbeatIntervalMs = heartbeatMs,
            client = client,
        )
    }

    @Test
    fun relayModeSendsAuthFrameFirstWithNv1AgentEnvelope() {
        val before = System.currentTimeMillis() / 1000
        val channel = newChannel(
            server.url("/t/route1234567890/api/v1/mobile/ws").toString(),
            secretProvider = { relaySecret },
        )
        channel.connect()

        val first = spy!!.received.poll(3, TimeUnit.SECONDS)
        assertTrue("relay 模式连接后必须有首条帧（auth）", first != null)
        val frame = Json.parseToJsonElement(first).jsonObject
        assertEquals("auth", frame["type"]?.toString()?.trim('"'))
        assertEquals("agent", frame["tokenType"]?.toString()?.trim('"'))
        val token = frame["token"]?.toString()?.trim('"').orEmpty()
        val parts = token.split(":")
        assertEquals("nv1", parts[0])
        assertEquals("agent", parts[1])
        val stamp = parts[2].toLong()
        assertTrue("issuedAt 应在连接时刻附近", stamp >= before && stamp <= System.currentTimeMillis() / 1000)
        assertEquals(16, parts[3].length)
        // 签名可按 protocol 口径复算：HMAC-SHA256(secret, "nv1:agent:{stamp}:{nonce}")
        val expected = TunnelTokenSigner.signTunnelToken(
            relaySecret, TunnelTokenSigner.TYPE_AGENT, stamp, parts[3],
        )
        assertEquals("信封须可由同一密钥复算验证", expected, token)
        channel.close()
    }

    @Test
    fun relayModeAuthFramePrecedesHeartbeat() {
        val channel = newChannel(
            server.url("/t/route1234567890/api/v1/mobile/ws").toString(),
            secretProvider = { relaySecret },
            heartbeatMs = 150,
        )
        channel.connect()
        val first = spy!!.received.poll(3, TimeUnit.SECONDS)
        assertEquals("auth", Json.parseToJsonElement(first).jsonObject["type"]?.toString()?.trim('"'))
        val second = spy!!.received.poll(3, TimeUnit.SECONDS)
        assertTrue("auth 之后才允许心跳", second != null && second.contains("ping"))
        channel.close()
    }

    @Test
    fun directModeSendsNoAuthFrame() {
        val channel = newChannel(
            server.url("/api/v1/mobile/ws").toString(),
            secretProvider = { relaySecret },
            heartbeatMs = 150,
        )
        channel.connect()
        val first = spy!!.received.poll(3, TimeUnit.SECONDS)
        assertTrue("直连模式首帧仍是心跳 ping", first != null && first.contains("ping"))
        channel.close()
    }

    @Test
    fun buildRelayAuthFrameUnitContract() {
        // 直连地址：恒不成帧
        assertNull(
            MobileWsChannel.buildRelayAuthFrame("ws://10.0.2.2:9527/api/v1/mobile/ws") { relaySecret },
        )
        // relay 地址但无密钥：不成帧
        assertNull(
            MobileWsChannel.buildRelayAuthFrame("wss://relay.example.com/t/route1/api/v1/mobile/ws") { null },
        )
        assertNull(
            MobileWsChannel.buildRelayAuthFrame("wss://relay.example.com/t/route1/api/v1/mobile/ws") { "  " },
        )
        // relay 地址 + 裸密钥：签成 nv1:agent 信封
        val framed = MobileWsChannel.buildRelayAuthFrame(
            "wss://relay.example.com/t/route1/api/v1/mobile/ws",
        ) { relaySecret } as JsonObject
        assertEquals("auth", framed["type"]?.toString()?.trim('"'))
        assertTrue(framed["token"]?.toString()?.trim('"').orEmpty().startsWith("nv1:agent:"))
        // 已有信封则原样用（不二次签发）
        val enveloped = "nv1:agent:1700000000:aabbccddeeff0011:cafebabe"
        val passthrough = MobileWsChannel.buildRelayAuthFrame(
            "wss://relay.example.com/t/route1/api/v1/mobile/ws",
        ) { enveloped } as JsonObject
        assertEquals(enveloped, passthrough["token"]?.toString()?.trim('"'))
    }
}
