package top.neurova.mobile.feature.servers

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import top.neurova.mobile.core.model.ServerProfile

/** P0-07：档案激活/删除/地址变更必须把凭据仓切换信号发到唯一装配层。 */
class ServersStoreCredentialScopeTest {

    @Test
    fun scanAndSwitchNotifyCredentialBindingBeforeReturning() {
        val store = ServersStore(MemoryPreferences()).apply { load() }
        val bindings = mutableListOf<Pair<String, String>?>()
        store.onActiveServerChanged = { bindings.add(it?.let { p -> p.id to p.baseUrl }) }

        val scannedId = store.ensureProfileForBaseUrl("https://evil.example/")
        assertEquals("https://evil.example", store.active?.baseUrl)
        assertEquals(scannedId to "https://evil.example", bindings.last())

        val trusted = store.newProfile("trusted", "https://trusted.example", ServerProfile.EntryMode.DIRECT)
        store.upsert(trusted)
        store.activate(trusted.id)
        assertEquals(trusted.id to "https://trusted.example", bindings.last())
        store.activate("missing")
        assertEquals(trusted.id, store.activeId)
    }

    @Test
    fun removingActiveServerClearsVaultAndBindsFallback() {
        val store = ServersStore(MemoryPreferences()).apply { load() }
        val first = store.active!!
        val second = store.newProfile("second", "https://second.example", ServerProfile.EntryMode.DIRECT)
        store.upsert(second)
        store.activate(second.id)
        val removed = mutableListOf<String>()
        val bindings = mutableListOf<String?>()
        store.onServerRemoved = { removed.add(it) }
        store.onActiveServerChanged = { bindings.add(it?.id) }

        store.remove(second.id)

        assertEquals(listOf(second.id), removed)
        assertEquals(first.id, store.activeId)
        assertEquals(listOf(first.id), bindings)
    }

    @Test
    fun changingActiveOriginRebindsSameServerId() {
        val store = ServersStore(MemoryPreferences()).apply { load() }
        val original = store.active!!
        val bindings = mutableListOf<Pair<String, String>>()
        store.onActiveServerChanged = { it?.let { p -> bindings.add(p.id to p.baseUrl) } }

        store.upsert(original.copy(baseUrl = "https://new.example"))

        assertEquals(listOf(original.id to "https://new.example"), bindings)
    }

    @Test
    fun deletingLastServerUnbindsCredentials() {
        val store = ServersStore(MemoryPreferences()).apply { load() }
        val id = store.activeId!!
        var binding: ServerProfile? = store.active
        store.onActiveServerChanged = { binding = it }

        store.remove(id)

        assertNull(store.active)
        assertNull(binding)
    }

    private class MemoryPreferences : PreferencesStore {
        private val values = mutableMapOf<String, String>()
        override fun readString(key: String): String? = values[key]
        override fun writeString(key: String, value: String) {
            values[key] = value
        }
    }
}
