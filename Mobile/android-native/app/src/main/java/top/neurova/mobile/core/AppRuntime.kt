package top.neurova.mobile.core

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import top.neurova.mobile.core.model.ServerProfile
import top.neurova.mobile.core.net.ChatSseChannel
import top.neurova.mobile.core.net.HttpChannel
import top.neurova.mobile.core.net.MobileWsChannel
import top.neurova.mobile.core.store.SecureVaultCredentialStore
import top.neurova.mobile.feature.auth.AuthStore
import top.neurova.mobile.feature.chat.ChatRepository
import top.neurova.mobile.feature.chat.ChatSessionController
import top.neurova.mobile.feature.pairing.PairingStore
import top.neurova.mobile.feature.servers.PreferencesStore
import top.neurova.mobile.feature.servers.ServersStore
import top.neurova.mobile.feature.servers.SharedPreferencesStore

/**
 * 运行时装配点（单一事实源）：凭证分仓 / 档案仓 / HTTP·SSE·WS 通道 / 认证·配对仓 全在此接线。
 * 各屏经 CompositionLocal 取用，禁止屏内自行 new 通道（防第二装配点漂移）。
 */
class AppRuntime(context: Context) {

    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    val credentials = SecureVaultCredentialStore(context.applicationContext)
    private val preferences: PreferencesStore = SharedPreferencesStore(context.applicationContext)
    val servers = ServersStore(preferences).apply { load() }

    private fun activeProfile(): ServerProfile =
        servers.active ?: ServerProfile(id = "default", name = "本机开发", baseUrl = "http://10.0.2.2:9527")

    val http = HttpChannel(::activeProfile, credentials, scope)
    val auth = AuthStore(http, credentials, servers)
    val pairing = PairingStore(http, credentials)
    val chatSse = ChatSseChannel(::activeProfile, http)
    val ws = MobileWsChannel(
        scope = scope,
        wsUrlProvider = { pairing.wsUrl.ifBlank { null } },
        ticketProvider = { pairing.ticket.ifBlank { null } },
        refreshTicket = { pairing.refreshTicket() },
    )
    val chatRepo = ChatRepository(http)
    val chatSessions = ChatSessionController(scope, ws, pairing, chatRepo)
}
