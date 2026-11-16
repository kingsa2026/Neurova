package top.neurova.mobile.core.model

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Agent 状态归一化（鸿蒙 AgentsApi.normStatus 同源语义）：
 * 后端 agent.py 的 status 取值 online/running/active/sleeping/error/...，
 * UI 徽标只认四态：active/sleeping/error/inactive。
 */
class AgentStatusNormalizeTest {

    @Test
    fun runningVariantsNormalizeToActive() {
        assertEquals(AgentStatus.ACTIVE, AgentStatus.normalize("running"))
        assertEquals(AgentStatus.ACTIVE, AgentStatus.normalize("online"))
        assertEquals(AgentStatus.ACTIVE, AgentStatus.normalize("active"))
    }

    @Test
    fun sleepingAndErrorKeepTheirOwnBadge() {
        assertEquals(AgentStatus.SLEEPING, AgentStatus.normalize("sleeping"))
        assertEquals(AgentStatus.ERROR, AgentStatus.normalize("error"))
    }

    @Test
    fun unknownOrBlankFallsBackToInactive() {
        assertEquals(AgentStatus.INACTIVE, AgentStatus.normalize("inactive"))
        assertEquals(AgentStatus.INACTIVE, AgentStatus.normalize(""))
        assertEquals(AgentStatus.INACTIVE, AgentStatus.normalize("something-else"))
    }

    @Test
    fun liveBackendAgentItemDecodesRealPayload() {
        // 2026-11-16 实测 GET /agents 首元素原样（created_at/owner_user_id 等可为 null）
        val payload = """
            {"agent_id":"default","name":"Neurova","description":"","model":"nex-n2.6",
             "provider":"moss","status":"running","created_at":null,"last_active":null,
             "memory_enabled":true,"tools_count":0,"owner_user_id":null,"group_id":null,
             "personality":"","constitution":"","exec_profile":null}
        """.trimIndent()
        val json = kotlinx.serialization.json.Json { ignoreUnknownKeys = true }
        val agent = json.decodeFromString(AgentItem.serializer(), payload)
        assertEquals("default", agent.agentId)
        assertEquals("Neurova", agent.name)
        assertEquals("nex-n2.6", agent.model)
        assertEquals("moss", agent.provider)
        assertEquals(true, agent.memoryEnabled)
        assertEquals(0, agent.toolsCount)
    }
}
