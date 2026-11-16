package top.neurova.mobile.feature.agents

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CoroutineScope
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import top.neurova.mobile.core.model.AgentItem
import top.neurova.mobile.core.net.HttpChannel

/**
 * Agent 单源（设计稿映射表：本地 AgentsStore 与后端同序）：
 * - 列表：GET /agents（裸数组，Wave H-W0 属主过滤：admin 全量、普通用户仅自有）；
 * - 当前 Agent：F5 聊天头部切换与 chat:send 的 agent_id 都读这里；
 * - 状态归一：AgentStatus.normalize（online/running/active → active）。
 */
class AgentsStore(
    private val http: HttpChannel,
    @Suppress("unused") private val scope: CoroutineScope,
) {

    var agents by mutableStateOf<List<AgentItem>>(emptyList())
        private set
    var currentAgentId by mutableStateOf("")
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    private val json = Json { ignoreUnknownKeys = true }

    suspend fun load() {
        loading = true
        error = null
        runCatching { http.unwrapData(http.getJson("/agents")) }
            .onSuccess { element ->
                agents = json.decodeFromJsonElement(ListSerializer(AgentItem.serializer()), element)
                if (currentAgentId.isBlank() || agents.none { it.agentId == currentAgentId }) {
                    currentAgentId = agents.firstOrNull()?.agentId ?: "default"
                }
            }
            .onFailure { error = it.message ?: "Agent 列表加载失败" }
        loading = false
    }

    fun switchAgent(agentId: String) {
        if (agentId.isNotBlank()) currentAgentId = agentId
    }

    fun current(): AgentItem? = agents.firstOrNull { it.agentId == currentAgentId }
}
