package top.neurova.mobile.core.store

import kotlinx.coroutines.async
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/** P0-07：加密键值适配器之上的 serverId/origin 分仓与旧全局凭证淘汰。 */
class ScopedCredentialStoreTest {

    @Test
    fun credentialsAreIsolatedByServerAndActiveBinding() {
        val store = newStore()
        store.saveTokens("a", "https://a.example/api/v1", "access-a", "refresh-a")
        store.saveTokens("b", "https://b.example/api/v1", "access-b", "refresh-b")
        store.savePairedIdentity("a", "https://a.example/api/v1", "pair-a", "secret-a")

        store.bindServer("a", "https://a.example")
        assertEquals("access-a", store.accessToken())
        assertEquals("refresh-a", store.refreshToken())
        assertEquals("pair-a" to "secret-a", store.pairedIdentity())

        store.bindServer("b", "https://b.example")
        assertEquals("access-b", store.accessToken())
        assertEquals("refresh-b", store.refreshToken())
        assertNull(store.pairedIdentity())

        store.clearServerBinding()
        assertEquals("", store.accessToken())
        assertEquals("", store.refreshToken())
        assertNull(store.pairedIdentity())
        assertThrows(IllegalStateException::class.java) { store.saveTokens("unbound", "unbound") }
    }

    @Test
    fun onlyExactNormalizedOriginCanReadCredentials() {
        val store = newStore()
        store.saveTokens("a", "https://EXAMPLE.com:443/api/v1", "access-a", "refresh-a")

        assertEquals("access-a", store.accessToken("a", "https://example.com/other/path?q=1"))
        assertEquals("refresh-a", store.refreshToken("a", "https://example.com"))
        assertEquals("", store.accessToken("a", "http://example.com"))
        assertEquals("", store.accessToken("a", "https://example.com:444"))
        assertEquals("", store.accessToken("a", "https://evil.example"))
        assertEquals("", store.accessToken("b", "https://example.com"))
    }

    @Test
    fun pairingCredentialsAreScopedAndServerRemovalClearsThem() {
        val store = newStore()
        store.saveTokens("a", "https://a.example", "access-a", "refresh-a")
        store.savePairedIdentity("a", "https://a.example", "pair-a", "secret-a")
        store.savePairedWsUrl("a", "https://a.example", "wss://a.example/ws")

        assertEquals("pair-a" to "secret-a", store.pairedIdentity("a", "https://a.example"))
        assertEquals("wss://a.example/ws", store.pairedWsUrl("a", "https://a.example"))
        assertNull(store.pairedIdentity("a", "https://other.example"))
        store.clearAuth("a")
        assertEquals("", store.accessToken("a", "https://a.example"))
        assertEquals("pair-a" to "secret-a", store.pairedIdentity("a", "https://a.example"))

        store.clearServer("a")
        assertNull(store.pairedIdentity("a", "https://a.example"))
        assertEquals("", store.pairedWsUrl("a", "https://a.example"))
    }

    @Test
    fun legacyGlobalKeysAreRemovedAndNeverRead() {
        val values = mutableMapOf(
            "neurova.auth.access_token" to "legacy-access",
            "neurova.auth.refresh_token" to "legacy-refresh",
            "neurova.pairing.device_secret" to "legacy-secret",
        )
        val store = ScopedCredentialStore(values::get) { updates ->
            updates.forEach { (key, value) -> if (value == null) values.remove(key) else values[key] = value }
        }

        store.bindServer("a", "https://a.example")
        assertEquals("", store.accessToken())
        assertEquals("", store.refreshToken())
        assertEquals("", store.deviceSecret())
        assertTrue(values.keys.none { it.startsWith("neurova.auth.") || it.startsWith("neurova.pairing.") })
    }

    @Test
    fun refreshSingleFlightIsPartitionedByServer() = runTest {
        val refresher = SingleFlightRefresher(backgroundScope)
        val calls = mutableMapOf<String, Int>()
        val a = async { refresher.run("a") { calls["a"] = (calls["a"] ?: 0) + 1; "token-a" } }
        val aJoined = async { refresher.run("a") { calls["a"] = (calls["a"] ?: 0) + 1; "token-a" } }
        val b = async { refresher.run("b") { calls["b"] = (calls["b"] ?: 0) + 1; "token-b" } }

        assertEquals("token-a", a.await())
        assertEquals("token-a", aJoined.await())
        assertEquals("token-b", b.await())
        assertEquals(1, calls["a"])
        assertEquals(1, calls["b"])
        assertFalse(calls.values.any { it != 1 })
    }

    @Test
    fun originNormalizationKeepsSchemeHostAndPortDistinct() {
        assertEquals("https://example.com:443", canonicalOrigin("https://EXAMPLE.com:443/api/v1"))
        assertEquals("http://example.com:80", canonicalOrigin("http://example.com/api/v1"))
        assertEquals("https://example.com:444", canonicalOrigin("https://example.com:444"))
        assertNull(canonicalOrigin("wss://example.com/ws"))
        assertNull(canonicalOrigin("not a url"))
    }

    private fun newStore(): ScopedCredentialStore {
        val values = mutableMapOf<String, String>()
        return ScopedCredentialStore(
            readValue = values::get,
            writeValues = { updates -> updates.forEach { (key, value) -> if (value == null) values.remove(key) else values[key] = value } },
        )
    }
}
