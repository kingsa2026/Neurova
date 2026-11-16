package top.neurova.mobile.core.model

import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 会话摘要线上契约（console.py get_chat_sessions 摘要形状原样，鸿蒙 SessionsApi 同源）：
 * 字段是 `id`/`pinned`——不是早期臆写的 `session_id`/`is_pinned`。
 * 红灯（2026-11-16）：现模型按 `session_id` 必填解码真实载荷即 MissingFieldException。
 */
class SessionWireTest {

    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun sessionSummaryDecodesRealBackendPayload() {
        val payload = """
            {"code":0,"message":"success","data":{"sessions":[
              {"id":"s-1","title":"周报草拟","agent_id":"atlas","created_at":"2026-11-16T09:00:00",
               "updated_at":"2026-11-16T10:24:00","pinned":true,"sort_order":1,
               "source_channel":"web","channel_name":""},
              {"id":"s-2","title":"Q3 数据报告整理","agent_id":"atlas","created_at":"2026-11-16T09:30:00",
               "updated_at":"2026-11-16T10:00:00","pinned":false,"sort_order":0,
               "source_channel":"","channel_name":""}
            ],"total":2}}
        """.trimIndent()
        val data = json.parseToJsonElement(payload).jsonObjectOrNull()!!["data"]!!.jsonObjectOrNull()!!
        val sessions = json.decodeFromJsonElement(ListSerializer(ChatSessionItem.serializer()), data["sessions"]!!)
        assertEquals(2, sessions.size)
        assertEquals("s-1", sessions[0].id)
        assertEquals("周报草拟", sessions[0].title)
        assertEquals("atlas", sessions[0].agentId)
        assertTrue(sessions[0].pinned)
        assertEquals("s-2", sessions[1].id)
        assertFalse(sessions[1].pinned)
        assertEquals(1, sessions[0].sortOrder)
    }

    @Test
    fun historyPayloadDecodesRoleAndContent() {
        val payload = """
            {"code":0,"message":"success","data":{"session_id":"s-1","messages":[
              {"role":"user","content":"把 Q3 各渠道转化数据汇总成报告"},
              {"role":"assistant","content":"好的，我将按四部分组织。"}
            ]}}
        """.trimIndent()
        val data = json.parseToJsonElement(payload).jsonObjectOrNull()!!["data"]!!.jsonObjectOrNull()!!
        val messages = json.decodeFromJsonElement(
            ListSerializer(ChatHistoryEntry.serializer()),
            data["messages"]!!,
        )
        assertEquals(2, messages.size)
        assertEquals("user", messages[0].role)
        assertEquals("把 Q3 各渠道转化数据汇总成报告", messages[0].content)
        assertEquals("assistant", messages[1].role)
    }
}

private fun kotlinx.serialization.json.JsonElement.jsonObjectOrNull(): kotlinx.serialization.json.JsonObject? =
    this as? kotlinx.serialization.json.JsonObject
