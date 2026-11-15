package top.neurova.mobile.feature.servers

import android.content.Context

/** 非敏感偏好持久化（档案列表；凭证一律走 CredentialStore 分仓，不落明文） */
interface PreferencesStore {
    fun readString(key: String): String?
    fun writeString(key: String, value: String)
}

class SharedPreferencesStore(context: Context) : PreferencesStore {
    private val prefs = context.getSharedPreferences("neurova.preferences", Context.MODE_PRIVATE)

    override fun readString(key: String): String? = prefs.getString(key, null)

    override fun writeString(key: String, value: String) {
        prefs.edit().putString(key, value).apply()
    }
}
