package top.neurova.mobile.core.net

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import top.neurova.mobile.core.model.ServerProfile
import top.neurova.mobile.core.store.CredentialStore
import top.neurova.mobile.core.store.ScopedCredentialStore

/** P0-07：服务器档案与 bearer/refresh 凭证必须同仓，切档不得把旧凭证发给新终端。 */
class HttpChannelServerCredentialTest {

    private lateinit var first: MockWebServer
    private lateinit var second: MockWebServer
    private val scope = CoroutineScope(Dispatchers.Unconfined)

    @Before
    fun setUp() {
        first = MockWebServer().apply { start() }
        second = MockWebServer().apply { start() }
    }

    @After
    fun tearDown() {
        runCatching { first.shutdown() }
        runCatching { second.shutdown() }
    }

    @Test
    fun switchingServerDoesNotReuseBearer() = runBlocking {
        var profile = profile("server-a", first.url("/").toString())
        val credentials = MemoryCredentials("trusted-jwt", "trusted-refresh", first.url("/").toString())
        val http = HttpChannel({ profile }, credentials, scope)
        first.enqueue(json())
        second.enqueue(json())

        http.getJson("/me")
        profile = profile("server-b", second.url("/").toString())
        http.getJson("/me")

        assertEquals("Bearer trusted-jwt", first.takeRequest().getHeader("Authorization"))
        assertNull("切换服务器后不得继承旧 bearer", second.takeRequest().getHeader("Authorization"))
    }

    @Test
    fun hostAndPortChangesDoNotReuseBearer() = runBlocking {
        val credentials = MemoryCredentials("trusted-jwt", "trusted-refresh", first.url("/").toString())
        var profile = profile("server-a", first.url("/").toString())
        val http = HttpChannel({ profile }, credentials, scope)
        first.enqueue(json())
        second.enqueue(json())

        http.getJson("/me")
        profile = profile("server-a", second.url("/").toString())
        http.getJson("/me")

        assertEquals("Bearer trusted-jwt", first.takeRequest().getHeader("Authorization"))
        assertNull("同 serverId 改 host/端口后不得继承旧 bearer", second.takeRequest().getHeader("Authorization"))
    }

    @Test
    fun interceptorCannotRedirectBearerToAnotherOrigin() = runBlocking {
        var profile = profile("server-a", first.url("/").toString())
        val credentials = MemoryCredentials("trusted-jwt", "trusted-refresh", first.url("/").toString())
        val rewritingClient = OkHttpClient.Builder()
            .addInterceptor { chain ->
                chain.proceed(chain.request().newBuilder().url(second.url("/api/v1/stolen")).build())
            }
            .build()
        val http = HttpChannel({ profile }, credentials, scope, rewritingClient)
        second.enqueue(json())

        http.getJson("/me")

        val stolen = second.takeRequest()
        assertEquals("/api/v1/stolen", stolen.path)
        assertNull("HTTP 实际目标 origin 不匹配时不得附旧 bearer", stolen.getHeader("Authorization"))
    }

    @Test
    fun crossOriginRedirectIsNotFollowed() = runBlocking {
        val profile = profile("server-a", first.url("/").toString())
        val credentials = MemoryCredentials("trusted-jwt", "trusted-refresh", first.url("/").toString())
        val http = HttpChannel({ profile }, credentials, scope)
        first.enqueue(MockResponse().setResponseCode(302).setHeader("Location", second.url("/stolen").toString()))

        val thrown = org.junit.Assert.assertThrows(ChannelHttpException::class.java) {
            runBlocking { http.getJson("/me") }
        }
        assertEquals(302, thrown.code)
        assertNull("跨 origin 重定向不得继续发送请求体或 bearer", second.takeRequest(1, java.util.concurrent.TimeUnit.SECONDS))
    }

    @Test
    fun sameServerIdOriginChangeDoesNotJoinRefresh() = runBlocking {
        var profile = profile("server-a", first.url("/").toString())
        val credentials = MemoryCredentials(
            "expired-jwt",
            "server-a-refresh",
            first.url("/").toString(),
            additionalBaseUrls = listOf(second.url("/").toString()),
        )
        val http = HttpChannel({ profile }, credentials, scope)
        first.enqueue(MockResponse().setResponseCode(401).setBody("{}"))
        first.enqueue(MockResponse().setBodyDelay(500, java.util.concurrent.TimeUnit.MILLISECONDS)
            .setBody("""{"access_token":"new-a","refresh_token":"new-a-refresh"}"""))
        first.enqueue(json())
        second.enqueue(MockResponse().setResponseCode(401).setBody("{}"))
        second.enqueue(MockResponse().setBody("""{"access_token":"new-b","refresh_token":"new-b-refresh"}"""))
        second.enqueue(json())

        val firstRequest = async(Dispatchers.IO) { http.getJson("/me") }
        assertEquals("/api/v1/auth/refresh", first.takeRequest(2, java.util.concurrent.TimeUnit.SECONDS)?.path)
        profile = profile("server-a", second.url("/").toString())
        val secondRequest = async(Dispatchers.IO) { http.getJson("/me") }
        firstRequest.await()
        secondRequest.await()

        assertEquals("/api/v1/me", first.takeRequest(2, java.util.concurrent.TimeUnit.SECONDS)?.path)
        assertEquals("同 serverId 改 origin 后续签不得加入旧 origin 的单飞任务", "/api/v1/auth/refresh",
            second.takeRequest(2, java.util.concurrent.TimeUnit.SECONDS)?.path)
        assertEquals("Bearer new-b", second.takeRequest(2, java.util.concurrent.TimeUnit.SECONDS)?.getHeader("Authorization"))
    }

    @Test
    fun refreshStaysOnRequestOriginAfterServerSwitch() = runBlocking {
        var profile = profile("server-a", first.url("/").toString())
        val credentials = MemoryCredentials("expired-jwt", "server-a-refresh", first.url("/").toString(), onRefresh = {
            profile = profile("server-b", second.url("/").toString())
        })
        val http = HttpChannel({ profile }, credentials, scope)
        first.enqueue(MockResponse().setResponseCode(401).setBody("{}"))
        first.enqueue(MockResponse().setBody("""{"access_token":"new-a","refresh_token":"new-a-refresh"}"""))
        first.enqueue(json())

        http.getJson("/me")

        val originalRequest = first.takeRequest()
        val originalRefresh = first.takeRequest(1, java.util.concurrent.TimeUnit.SECONDS)
        val replay = first.takeRequest(1, java.util.concurrent.TimeUnit.SECONDS)
        assertEquals("/api/v1/me", originalRequest.path)
        assertEquals("Bearer expired-jwt", originalRequest.getHeader("Authorization"))
        assertEquals("续签必须留在原服务器 origin", "/api/v1/auth/refresh", originalRefresh?.path)
        assertEquals("在途请求的重放仍留在原档案", "/api/v1/me", replay?.path)
        assertEquals("Bearer new-a", replay?.getHeader("Authorization"))
        assertNull("切档不得接管在途请求", second.takeRequest(1, java.util.concurrent.TimeUnit.SECONDS))
    }

    private fun profile(id: String, baseUrl: String) = ServerProfile(id = id, name = id, baseUrl = baseUrl.trimEnd('/'))

    private fun json() = MockResponse().setHeader("Content-Type", "application/json").setBody("{}")

    private class MemoryCredentials(
        access: String,
        refresh: String,
        baseUrl: String,
        private val onRefresh: () -> Unit = {},
        private val additionalBaseUrls: List<String> = emptyList(),
    ) : CredentialStore {
        private val values = mutableMapOf<String, String>()
        private val delegate = ScopedCredentialStore(
            readValue = values::get,
            writeValues = { updates -> updates.forEach { (key, value) -> if (value == null) values.remove(key) else values[key] = value } },
        )

        init {
            delegate.saveTokens("server-a", baseUrl, access, refresh)
            additionalBaseUrls.forEach { delegate.saveTokens("server-a", it, access, refresh) }
        }

        override fun accessToken(): String = delegate.accessToken()
        override fun refreshToken(): String = delegate.refreshToken()
        override fun deviceSecret(): String = ""
        override fun pairedIdentity(): Pair<String, String>? = null
        override fun pairedWsUrl(): String = ""
        override fun saveTokens(access: String, refresh: String) = Unit
        override fun savePairedIdentity(pairingId: String, deviceSecret: String) = Unit
        override fun savePairedWsUrl(url: String) = Unit
        override fun clearAuth() = Unit
        override fun accessToken(serverId: String, origin: String) = delegate.accessToken(serverId, origin)
        override fun refreshToken(serverId: String, origin: String): String {
            onRefresh()
            return delegate.refreshToken(serverId, origin)
        }
        override fun saveTokens(serverId: String, origin: String, access: String, refresh: String) =
            delegate.saveTokens(serverId, origin, access, refresh)
        override fun clearAuth(serverId: String) = delegate.clearAuth(serverId)
    }
}
