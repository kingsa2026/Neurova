package top.neurova.mobile.core.store

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.async
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/**
 * 凭证安全存储（手机客户端设计方案 §9.2 分仓口径）：
 * - refresh_token / device_secret / access_token：Android Keystore 加密存储；
 * - 每份凭证只属于一个 serverId，且只在该档案的规范化 origin 完全相同时可用；
 * - connect_ticket 仍仅内存，永不持久化。
 *
 * 无参入口保留给未显式传档案的既有调用方，统一读取当前绑定档案；未绑定时 fail-closed。
 * HTTP 与续签使用带 serverId/origin 的入口，不依赖“当前激活档案”这一可变状态。
 */
interface CredentialStore {
    fun accessToken(): String
    fun refreshToken(): String
    fun deviceSecret(): String
    fun pairedIdentity(): Pair<String, String>?
    /** 配对时服务器回的 WS 回连地址（重启恢复用；地址非凭证，可落加密存储） */
    fun pairedWsUrl(): String
    fun saveTokens(access: String, refresh: String)
    fun savePairedIdentity(pairingId: String, deviceSecret: String)
    fun savePairedWsUrl(url: String)
    fun clearAuth()

    fun accessToken(serverId: String, origin: String): String = accessToken()
    fun refreshToken(serverId: String, origin: String): String = refreshToken()
    fun deviceSecret(serverId: String, origin: String): String = deviceSecret()
    fun pairedIdentity(serverId: String, origin: String): Pair<String, String>? = pairedIdentity()
    fun pairedWsUrl(serverId: String, origin: String): String = pairedWsUrl()
    fun saveTokens(serverId: String, origin: String, access: String, refresh: String) = saveTokens(access, refresh)
    fun savePairedIdentity(serverId: String, origin: String, pairingId: String, deviceSecret: String) =
        savePairedIdentity(pairingId, deviceSecret)
    fun savePairedWsUrl(serverId: String, origin: String, url: String) = savePairedWsUrl(url)
    fun clearAuth(serverId: String) = clearAuth()
    fun bindServer(serverId: String, baseUrl: String) = Unit
    fun clearServerBinding() = Unit
    fun clearServer(serverId: String) = clearAuth(serverId)
}

private const val KEY_ACCESS = "neurova.auth.access_token"
private const val KEY_REFRESH = "neurova.auth.refresh_token"
private const val KEY_PAIRING_ID = "neurova.pairing.pairing_id"
private const val KEY_DEVICE_SECRET = "neurova.pairing.device_secret"
private const val KEY_PAIRING_WS_URL = "neurova.pairing.ws_url"
private val LEGACY_KEYS = listOf(KEY_ACCESS, KEY_REFRESH, KEY_PAIRING_ID, KEY_DEVICE_SECRET, KEY_PAIRING_WS_URL)

/** origin 只比较协议、规范化主机与显式端口；路径、query、默认端口大小写差异不参与身份。 */
internal fun canonicalOrigin(raw: String): String? {
    val url = raw.toHttpUrlOrNull() ?: return null
    if (url.scheme != "http" && url.scheme != "https") return null
    return "${url.scheme}://${url.host}:${url.port}"
}

private data class BoundServer(val serverId: String, val origin: String)

/** 可独立测试的分仓实现；生产适配器只负责提供 Keystore 加密后的键值读写。 */
internal class ScopedCredentialStore(
    private val readValue: (String) -> String?,
    private val writeValues: (Map<String, String?>) -> Unit,
) : CredentialStore {
    private val accessByServer = ConcurrentHashMap<String, String>()
    @Volatile private var bound: BoundServer? = null
    @Volatile private var migrated = false

    private fun migrateLegacyKeys() {
        if (migrated) return
        synchronized(this) {
            if (!migrated) {
                // 旧全局 key 无法证明属于哪台服务器，直接淘汰，绝不迁移或继续读取。
                writeValues(LEGACY_KEYS.associateWith { null })
                migrated = true
            }
        }
    }

    private fun activeBound(): BoundServer = checkNotNull(bound) { "当前服务器凭据仓尚未绑定" }
    private fun key(serverId: String, suffix: String): String =
        "neurova.server.${Base64.getUrlEncoder().withoutPadding().encodeToString(serverId.toByteArray())}.$suffix"
    private fun normalizedOrigin(origin: String): String =
        checkNotNull(canonicalOrigin(origin)) { "非法服务器 origin: $origin" }
    private fun matches(serverId: String, origin: String): Boolean =
        readValue(key(serverId, "origin")) == normalizedOrigin(origin)

    override fun bindServer(serverId: String, baseUrl: String) {
        require(serverId.isNotBlank()) { "serverId 不得为空" }
        bound = BoundServer(serverId, normalizedOrigin(baseUrl))
    }

    override fun clearServerBinding() {
        bound = null
    }

    override fun accessToken(): String = bound?.let { accessToken(it.serverId, it.origin) }.orEmpty()
    override fun refreshToken(): String = bound?.let { refreshToken(it.serverId, it.origin) }.orEmpty()
    override fun deviceSecret(): String = bound?.let { deviceSecret(it.serverId, it.origin) }.orEmpty()
    override fun pairedIdentity(): Pair<String, String>? = bound?.let { pairedIdentity(it.serverId, it.origin) }
    override fun pairedWsUrl(): String = bound?.let { pairedWsUrl(it.serverId, it.origin) }.orEmpty()

    override fun accessToken(serverId: String, origin: String): String {
        migrateLegacyKeys()
        if (!matches(serverId, origin)) return ""
        return accessByServer[serverId] ?: readValue(key(serverId, "access")).orEmpty().also {
            if (it.isEmpty()) accessByServer.remove(serverId) else accessByServer[serverId] = it
        }
    }

    override fun refreshToken(serverId: String, origin: String): String {
        migrateLegacyKeys()
        return if (matches(serverId, origin)) readValue(key(serverId, "refresh")).orEmpty() else ""
    }

    override fun deviceSecret(serverId: String, origin: String): String {
        migrateLegacyKeys()
        return if (matches(serverId, origin)) readValue(key(serverId, "device_secret")).orEmpty() else ""
    }

    override fun pairedIdentity(serverId: String, origin: String): Pair<String, String>? {
        migrateLegacyKeys()
        if (!matches(serverId, origin)) return null
        val pairingId = readValue(key(serverId, "pairing_id")) ?: return null
        val secret = readValue(key(serverId, "device_secret")) ?: return null
        return pairingId to secret
    }

    override fun pairedWsUrl(serverId: String, origin: String): String {
        migrateLegacyKeys()
        return if (matches(serverId, origin)) readValue(key(serverId, "ws_url")).orEmpty() else ""
    }

    override fun saveTokens(access: String, refresh: String) {
        val target = activeBound()
        saveTokens(target.serverId, target.origin, access, refresh)
    }

    override fun saveTokens(serverId: String, origin: String, access: String, refresh: String) {
        migrateLegacyKeys()
        val normalized = normalizedOrigin(origin)
        val prefix = key(serverId, "")
        if (access.isEmpty()) accessByServer.remove(serverId) else accessByServer[serverId] = access
        writeValues(mapOf(
            "${prefix}origin" to normalized,
            "${prefix}access" to access,
            "${prefix}refresh" to refresh,
        ))
    }

    override fun savePairedIdentity(pairingId: String, deviceSecret: String) {
        val target = activeBound()
        savePairedIdentity(target.serverId, target.origin, pairingId, deviceSecret)
    }

    override fun savePairedIdentity(serverId: String, origin: String, pairingId: String, deviceSecret: String) {
        migrateLegacyKeys()
        val prefix = key(serverId, "")
        writeValues(mapOf(
            "${prefix}origin" to normalizedOrigin(origin),
            "${prefix}pairing_id" to pairingId,
            "${prefix}device_secret" to deviceSecret,
        ))
    }

    override fun savePairedWsUrl(url: String) {
        val target = activeBound()
        savePairedWsUrl(target.serverId, target.origin, url)
    }

    override fun savePairedWsUrl(serverId: String, origin: String, url: String) {
        migrateLegacyKeys()
        val prefix = key(serverId, "")
        writeValues(mapOf("${prefix}origin" to normalizedOrigin(origin), "${prefix}ws_url" to url))
    }

    override fun clearAuth() {
        bound?.let { clearAuth(it.serverId) }
    }

    override fun clearAuth(serverId: String) {
        migrateLegacyKeys()
        accessByServer.remove(serverId)
        val prefix = key(serverId, "")
        writeValues(mapOf("${prefix}access" to null, "${prefix}refresh" to null))
    }

    override fun clearServer(serverId: String) {
        migrateLegacyKeys()
        accessByServer.remove(serverId)
        val prefix = key(serverId, "")
        writeValues(listOf("origin", "access", "refresh", "pairing_id", "device_secret", "ws_url")
            .associate { "${prefix}$it" to null })
    }
}

private fun secureCredentialStore(context: Context): CredentialStore {
    val prefs by lazy {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            "neurova.secure.vault",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }
    return ScopedCredentialStore(
        readValue = { key -> prefs.getString(key, null) },
        writeValues = { values ->
            prefs.edit().apply {
                values.forEach { (key, value) -> if (value == null) remove(key) else putString(key, value) }
            }.apply()
        },
    )
}

class SecureVaultCredentialStore(context: Context) : CredentialStore by secureCredentialStore(context)

/** 401 单飞续签按 serverId 分组；不同服务器的刷新不得互相复用 Deferred。 */
class SingleFlightRefresher(private val scope: CoroutineScope) {
    private val mutex = Mutex()
    private val inFlight = mutableMapOf<String, Deferred<String>>()

    suspend fun run(key: String, refresh: suspend () -> String): String {
        val mine = mutex.withLock {
            inFlight[key]?.takeIf { it.isActive } ?: scope.async { refresh() }.also { inFlight[key] = it }
        }
        return try {
            mine.await()
        } finally {
            mutex.withLock { if (inFlight[key] === mine) inFlight.remove(key) }
        }
    }
}
