package top.neurova.mobile.core.model

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 工作台统计解析（GET /home/data 裸 dict，无信封）——样本取自 2026-11-16 后端实测返回。
 * 只取 UI 要展示的字段；缺字段按 0 兜底（新装实例 stats 可能缺键）。
 */
class WorkbenchStatsTest {

    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun parsesRealHomeDataPayload() {
        val payload = """
            {"welcome_message":"欢迎回来 Neurova",
             "quick_stats":{"total_conversations":700,"total_memories":2315,"total_skills":0},
             "stats":{"agent_count":3,"conversation_count":700,"memory_count":2315,
                      "token_consumption":1282392,"plugin_count":0,"public_skill_count":0,
                      "sleep_count":0,"sleep_log_count":0,"llm_call_count":191,
                      "evolution_count":0,"custom_skill_count":0,"skill_iteration_count":0},
             "memory_categories":{"short_term":0,"long_term":0,"episodic":0,"semantic":0}}
        """.trimIndent()
        val stats = WorkbenchStats.fromHomeData(json.parseToJsonElement(payload))
        assertEquals("欢迎回来 Neurova", stats.welcomeMessage)
        assertEquals(3, stats.agentCount)
        assertEquals(700, stats.conversationCount)
        assertEquals(2315, stats.memoryCount)
        assertEquals(1282392L, stats.tokenConsumption)
        assertEquals(191, stats.llmCallCount)
        assertEquals(0, stats.pluginCount)
    }

    @Test
    fun missingKeysFallBackToZero() {
        val stats = WorkbenchStats.fromHomeData(json.parseToJsonElement("{}"))
        assertEquals("", stats.welcomeMessage)
        assertEquals(0, stats.agentCount)
        assertEquals(0, stats.tokenConsumption)
    }
}
