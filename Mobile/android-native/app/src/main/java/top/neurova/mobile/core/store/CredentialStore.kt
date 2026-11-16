package top.neurova.mobile.core.store

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.async
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * 凭证安全存储（手机客户端设计方案 §9.2 分仓口径）：
 * - refresh_token / device_secret：Android Keystore 加密（EncryptedSharedPreferences），不落明文；
 * - access_token：内存优先 + 安全存储兜底（重启恢复用）；
 * - connect_ticket：一次性 60s，仅内存，永不持久化。
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
}

private const val KEY_ACCESS = "neurova.auth.access_token"
private const val KEY_REFRESH = "neurova.auth.refresh_token"
private const val KEY_PAIRING_ID = "neurova.pairing.pairing_id"
private const val KEY_DEVICE_SECRET = "neurova.pairing.device_secret"
private const val KEY_PAIRING_WS_URL = "neurova.pairing.ws_url"

class SecureVaultCredentialStore(context: Context) : CredentialStore {

    private val prefs by lazy {
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

    @Volatile private var accessInMemory: String? = null

    override fun accessToken(): String = accessInMemory ?: prefs.getString(KEY_ACCESS, null).orEmpty().also {
        accessInMemory = it
    }

    override fun refreshToken(): String = prefs.getString(KEY_REFRESH, null).orEmpty()

    override fun deviceSecret(): String = prefs.getString(KEY_DEVICE_SECRET, null).orEmpty()

    override fun pairedIdentity(): Pair<String, String>? {
        val pairingId = prefs.getString(KEY_PAIRING_ID, null) ?: return null
        val secret = prefs.getString(KEY_DEVICE_SECRET, null) ?: return null
        return pairingId to secret
    }

    override fun pairedWsUrl(): String = prefs.getString(KEY_PAIRING_WS_URL, null).orEmpty()

    override fun saveTokens(access: String, refresh: String) {
        accessInMemory = access
        prefs.edit().putString(KEY_ACCESS, access).putString(KEY_REFRESH, refresh).apply()
    }

    override fun savePairedIdentity(pairingId: String, deviceSecret: String) {
        prefs.edit().putString(KEY_PAIRING_ID, pairingId).putString(KEY_DEVICE_SECRET, deviceSecret).apply()
    }

    override fun savePairedWsUrl(url: String) {
        prefs.edit().putString(KEY_PAIRING_WS_URL, url).apply()
    }

    override fun clearAuth() {
        accessInMemory = null
        prefs.edit().remove(KEY_ACCESS).remove(KEY_REFRESH).apply()
    }
}

/** 401 单飞续签协调（多请求并发 401 时仅放行一个 refresh，其余等待复用同一 Deferred；批次结束自然失效） */
class SingleFlightRefresher(private val scope: CoroutineScope) {
    private val mutex = Mutex()
    private var inFlight: Deferred<String>? = null

    suspend fun run(refresh: suspend () -> String): String {
        val mine = mutex.withLock {
            val existing = inFlight
            if (existing != null && existing.isActive) {
                existing
            } else {
                scope.async { refresh() }.also { inFlight = it }
            }
        }
        return mine.await()
    }
}
