package top.neurova.mobile.feature.servers

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import java.util.UUID
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import top.neurova.mobile.core.model.ServerProfile

/**
 * 服务器档案仓（手机客户端设计方案 §4.5；对齐 Mobile/android/src/stores/servers.ts）。
 * 后端地址一律来自档案，代码不写死服务器；档案列表持久化走 PreferencesStore（JSON 序列化）。
 */
class ServersStore(private val persistence: PreferencesStore) {

    @Serializable
    private data class PersistedProfile(
        val id: String,
        val name: String,
        val baseUrl: String,
        val entryMode: String,
        val lastAccount: String? = null,
        val lastConnectedAt: Long? = null,
    )

    val profiles = mutableStateListOf<ServerProfile>()
    var activeId by mutableStateOf<String?>(null)
        private set

    val active: ServerProfile? get() = profiles.firstOrNull { it.id == activeId }
    val apiBase: String get() = active?.apiBase ?: ""

    fun load() {
        val raw = persistence.readString(PROFILES_KEY)
        val activeRaw = persistence.readString(ACTIVE_KEY)
        if (raw != null) {
            runCatching {
                profiles.clear()
                profiles.addAll(
                    json.decodeFromString<List<PersistedProfile>>(raw).map {
                        ServerProfile(
                            id = it.id,
                            name = it.name,
                            baseUrl = it.baseUrl,
                            entryMode = if (it.entryMode == "relay") ServerProfile.EntryMode.RELAY else ServerProfile.EntryMode.DIRECT,
                            lastAccount = it.lastAccount,
                            lastConnectedAt = it.lastConnectedAt,
                        )
                    },
                )
            }
        }
        if (profiles.isEmpty()) {
            profiles.add(defaultProfile())
            activeId = profiles.first().id
            persist()
        }
        activeId = activeRaw ?: profiles.firstOrNull()?.id
    }

    fun upsert(profile: ServerProfile) {
        val index = profiles.indexOfFirst { it.id == profile.id }
        if (index >= 0) profiles[index] = profile else profiles.add(profile)
        persist()
    }

    fun activate(id: String) {
        activeId = id
        persistence.writeString(ACTIVE_KEY, id)
    }

    fun markConnected(account: String) {
        val index = profiles.indexOfFirst { it.id == activeId }
        if (index >= 0) {
            profiles[index] = profiles[index].copy(lastAccount = account, lastConnectedAt = System.currentTimeMillis())
            persist()
        }
    }

    fun newProfile(name: String, baseUrl: String, entryMode: ServerProfile.EntryMode): ServerProfile =
        ServerProfile(id = "srv-" + UUID.randomUUID().toString().take(8), name = name, baseUrl = baseUrl, entryMode = entryMode)

    private fun persist() {
        val payload = profiles.map {
            PersistedProfile(
                id = it.id,
                name = it.name,
                baseUrl = it.baseUrl,
                entryMode = if (it.entryMode == ServerProfile.EntryMode.RELAY) "relay" else "direct",
                lastAccount = it.lastAccount,
                lastConnectedAt = it.lastConnectedAt,
            )
        }
        persistence.writeString(PROFILES_KEY, json.encodeToString(payload))
    }

    /** 首启引导档案：本机开发（真机使用时用户改为实际内网/中继地址，同 Vue 端 DEFAULT_SERVER_PROFILE） */
    private fun defaultProfile() = ServerProfile(
        id = "default",
        name = "本机开发",
        baseUrl = "http://10.0.2.2:9527",
        entryMode = ServerProfile.EntryMode.DIRECT,
    )

    private companion object {
        const val PROFILES_KEY = "neurova.servers.profiles"
        const val ACTIVE_KEY = "neurova.servers.active_id"
        val json = Json { ignoreUnknownKeys = true }
    }
}
