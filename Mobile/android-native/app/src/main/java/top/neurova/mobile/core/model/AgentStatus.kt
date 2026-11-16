package top.neurova.mobile.core.model

/**
 * Agent 状态四态（UI 徽标口径，鸿蒙 AgentsApi.normStatus 同源语义）：
 * 后端 agent.py 的原始取值（online/running/active/sleeping/error/...）在此归一。
 */
enum class AgentStatus {
    ACTIVE,
    SLEEPING,
    ERROR,
    INACTIVE,
    ;

    companion object {
        fun normalize(raw: String?): AgentStatus = when (raw) {
            "running", "online", "active" -> ACTIVE
            "sleeping" -> SLEEPING
            "error" -> ERROR
            else -> INACTIVE
        }
    }
}
