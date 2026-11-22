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
import top.neurova.mobile.feature.admin.AdminRepository
import top.neurova.mobile.feature.admin.EvolutionRepository
import top.neurova.mobile.feature.aigc.AigcRepository
import top.neurova.mobile.feature.agents.AgentsStore
import top.neurova.mobile.feature.auth.AuthStore
import top.neurova.mobile.feature.chat.ChatRepository
import top.neurova.mobile.feature.chat.ChatSessionController
import top.neurova.mobile.feature.chat.ToolActionRepository
import top.neurova.mobile.feature.knowledge.KnowledgeRepository
import top.neurova.mobile.feature.models.ModelsRepository
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

    /** 当前生效档案（屏内拼产物绝对地址等场景取用；默认兜底仍单源在 activeProfile） */
    fun currentProfile(): ServerProfile = activeProfile()

    val http = HttpChannel(::activeProfile, credentials, scope)
    val auth = AuthStore(http, credentials, servers)
    val pairing = PairingStore(http, credentials)
    val chatSse = ChatSseChannel(::activeProfile, http)
    val toolActions = ToolActionRepository(http)
    val ws = MobileWsChannel(
        scope = scope,
        wsUrlProvider = { pairing.wsUrl.ifBlank { null } },
        ticketProvider = { pairing.ticket.ifBlank { null } },
        refreshTicket = { pairing.refreshTicket() },
        // U9/U16 relay 鉴权新形态：relay 模式连接后首条 auth 帧的裸密钥取当前配对
        // ticket（本地签 nv1:agent 信封后再上线，裸密钥不进 URL/日志）；直连模式不签发。
        relayAuthSecretProvider = { pairing.ticket.ifBlank { null } },
    )
    val chatRepo = ChatRepository(http)
    val chatSessions = ChatSessionController(scope, ws, pairing, chatRepo, toolActions)
    val agents = AgentsStore(http, scope)
    val knowledgeRepo = KnowledgeRepository(http)
    val modelsRepo = ModelsRepository(http)
    val adminRepo = AdminRepository(http)
    val evolutionRepo = EvolutionRepository(http)
    val aigcRepo = AigcRepository(http)
}
