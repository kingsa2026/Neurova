package top.neurova.mobile.core

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import top.neurova.mobile.core.model.ServerProfile
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
 * 运行时装配点（单一事实源）：凭证分仓 / 档案仓 / HTTP·WS 通道 / 认证·配对仓 全在此接线。
 * 各屏经 CompositionLocal 取用，禁止屏内自行 new 通道（防第二装配点漂移）。
 */
class AppRuntime(context: Context) {

    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    val credentials = SecureVaultCredentialStore(context.applicationContext)
    /** 非敏感偏好（档案/游标/推送设备号）；凭证一律走 credentials 加密分仓 */
    val preferences: PreferencesStore = SharedPreferencesStore(context.applicationContext)
    val servers = ServersStore(preferences).apply { load() }

    private fun activeProfile(): ServerProfile =
        servers.active ?: ServerProfile(id = "default", name = "本机开发", baseUrl = "http://10.0.2.2:9527")

    /** 当前生效档案（屏内拼产物绝对地址等场景取用；默认兜底仍单源在 activeProfile） */
    fun currentProfile(): ServerProfile = activeProfile()

    val http = HttpChannel(::activeProfile, credentials, scope)
    val auth = AuthStore(http, credentials, servers)
    val pairing = PairingStore(http, credentials)
    val toolActions = ToolActionRepository(http)
    val ws = MobileWsChannel(
        scope = scope,
        wsUrlProvider = { pairing.wsUrl.ifBlank { null } },
        ticketProvider = { pairing.ticket.ifBlank { null } },
        refreshTicket = { pairing.refreshTicket() },
        // D3/B7：账本游标跨进程持久化——离线入队的遥控帧在 App 重启后仍能补拉
        lastSeqRestore = {
            preferences.readString("neurova.ws.last_server_seq")?.toIntOrNull() ?: 0
        },
        lastSeqPersist = { seq ->
            runCatching { preferences.writeString("neurova.ws.last_server_seq", seq.toString()) }
        },
        inboxRestore = { preferences.readString("neurova.ws.inbox").orEmpty() },
        inboxPersist = { raw ->
            runCatching { preferences.writeString("neurova.ws.inbox", raw) }
        },
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

    /** 设备桥端上能力授权（D4：默认全关；A6 授权页读写） */
    val deviceAuth = top.neurova.mobile.core.capability.DeviceAuthStore(preferences)

    /**
     * 设备桥能力快照上报（device:hello）的唯一出口：连接建立（AUTHED）与
     * 授权变更（授权页开关）两个时机都从这里出——hello 目录与服务端登记的
     * 能力子集保持单一事实源，不因开关时机滞后到下次重连。
     */
    fun sendDeviceHello() {
        val enabled = top.neurova.mobile.core.capability.DeviceCapabilities.CLAIMED.filter {
            deviceAuth.isEnabled(it)
        }
        ws.sendDeviceFrame(
            top.neurova.mobile.core.protocol.DeviceBridgeEvents.buildHello(
                platform = top.neurova.mobile.core.capability.DeviceCapabilities.PLATFORM,
                protocolVersion = top.neurova.mobile.core.capability.DeviceCapabilities.PROTOCOL_VERSION,
                capabilities = enabled,
                appState = top.neurova.mobile.core.capability.AppStateTracker.current,
            ),
        )
    }

    companion object {
        /**
         * 进程级单例（DCL + 双检，仓规）：设备桥前台服务（DeviceBridgeService）
         * 不经 Compose 树，也要取到同一份装配——单一装配点，不另起第二套通道。
         */
        @Volatile
        private var instance: AppRuntime? = null

        fun instanceOrNull(): AppRuntime? = instance

        fun instance(context: Context): AppRuntime =
            instance ?: synchronized(this) {
                instance ?: AppRuntime(context.applicationContext).also { instance = it }
            }
    }
}
