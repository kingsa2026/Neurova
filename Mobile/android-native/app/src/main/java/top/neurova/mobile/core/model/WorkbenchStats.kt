package top.neurova.mobile.core.model

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * 工作台统计（GET /home/data 裸 dict，无信封；后端事实源 neurova/api/endpoints/home.py）。
 * 只取 UI 展示字段；缺键按 0 兜底（新装实例 stats 可能缺键）。
 */
data class WorkbenchStats(
    val welcomeMessage: String,
    val agentCount: Int,
    val conversationCount: Int,
    val memoryCount: Int,
    val tokenConsumption: Long,
    val llmCallCount: Int,
    val pluginCount: Int,
) {
    companion object {
        fun fromHomeData(payload: JsonElement): WorkbenchStats {
            val root = payload as? JsonObject ?: return empty()
            val stats = root["stats"] as? JsonObject ?: JsonObject(emptyMap())
            return WorkbenchStats(
                welcomeMessage = root["welcome_message"]?.jsonPrimitive?.content ?: "",
                agentCount = stats.intOf("agent_count"),
                conversationCount = stats.intOf("conversation_count"),
                memoryCount = stats.intOf("memory_count"),
                tokenConsumption = stats.longOf("token_consumption"),
                llmCallCount = stats.intOf("llm_call_count"),
                pluginCount = stats.intOf("plugin_count"),
            )
        }

        private fun empty() = WorkbenchStats("", 0, 0, 0, 0L, 0, 0)

        private fun JsonObject.intOf(key: String): Int = (this[key] as? kotlinx.serialization.json.JsonPrimitive)
            ?.content?.toIntOrNull() ?: 0

        private fun JsonObject.longOf(key: String): Long = (this[key] as? kotlinx.serialization.json.JsonPrimitive)
            ?.content?.toLongOrNull() ?: 0L
    }
}
