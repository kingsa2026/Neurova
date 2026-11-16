package top.neurova.mobile.core.model

import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 知识条目线上契约（GET /knowledge 信封 data:{items,total,page,page_size}，
 * item 字段为后端 knowledge_core.py 的 snake_case 原样；鸿蒙 KnowledgeApi 同源）。
 * 样本取自 2026-11-16 后端实测（content 为长文本，UI 只展示元信息）。
 */
class KnowledgeWireTest {

    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun knowledgeItemDecodesRealBackendPayload() {
        // created_at/updated_at 实测是浮点秒（1791279148.074471），Long 解码即炸——本条钉死该契约
        val payload = """
            {"knowledge_id":"51c3fffa-700f-4476-8ac5-40e00a8721f5","title":"README",
             "content":"# Neurova 文档总索引（长文本略）","category":"规范","tags":["索引"],
             "source":"import","confidence":1.0,"created_at":1791279148.074471,
             "updated_at":1791279148.074471,"visibility":"private","owner_user_id":"3",
             "shared_with":[],"chunk_count":73,"chunk_hits":[],"metadata":{}}
        """.trimIndent()
        val item = json.decodeFromString(KnowledgeEntry.serializer(), payload)
        assertEquals("51c3fffa-700f-4476-8ac5-40e00a8721f5", item.knowledgeId)
        assertEquals("README", item.title)
        assertEquals("规范", item.category)
        assertEquals("private", item.visibility)
        assertTrue(item.tags.contains("索引"))
        assertEquals(1791279148.074471, item.createdAt!!, 0.001)
    }

    @Test
    fun knowledgeListPayloadDecodesEnvelopeData() {
        val payload = """
            {"items":[
              {"knowledge_id":"k1","title":"Q3 渠道转化口径定义","content":"口径…","category":"规范",
               "tags":[],"source":"manual","confidence":1.0,"created_at":1791279148.07,
               "updated_at":1791279148.07,"visibility":"public","owner_user_id":"3","shared_with":[]}
            ],"total":218,"page":1,"page_size":2}
        """.trimIndent()
        val list = json.decodeFromString(KnowledgeListPayload.serializer(), payload)
        assertEquals(218, list.total)
        assertEquals(1, list.items.size)
        assertEquals("Q3 渠道转化口径定义", list.items[0].title)
    }

    @Test
    fun currentUserDecodesRealAuthMePayload() {
        // 2026-11-16 实测 /auth/me：多出 user_id/allowed_modules/created_at 键，缺 tenant 键
        val payload = """
            {"id":"3","user_id":"3","username":"admin","email":"","role":"admin",
             "allowed_modules":[],"created_at":null}
        """.trimIndent()
        val user = json.decodeFromString(CurrentUser.serializer(), payload)
        assertEquals("admin", user.username)
        assertEquals("admin", user.role)
        assertEquals("3", user.id)
    }
}
