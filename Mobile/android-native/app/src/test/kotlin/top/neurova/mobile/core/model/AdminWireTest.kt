package top.neurova.mobile.core.model

import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * P8 次级页线上契约——样本取自 2026-11-16 后端实测：
 * GET /providers、/models、/enhanced-users、/groups 全部为**裸数组/裸对象**（无信封）。
 * 注意 /models 的 context_window/max_tokens 实测可为 null，模型字段必须可空。
 */
class AdminWireTest {

    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun providerInfoDecodesRealPayload() {
        val payload = """
            {"provider_id":"amd","name":"AMD","provider_type":"openai",
             "base_url":"https://developer.amd.com.cn/radeon/api/v1","is_active":true,
             "status":"unknown","models_count":6,"health":"unknown","api_key_configured":true}
        """.trimIndent()
        val provider = json.decodeFromString(ProviderInfo.serializer(), payload)
        assertEquals("amd", provider.providerId)
        assertEquals("AMD", provider.name)
        assertEquals("openai", provider.providerType)
        assertTrue(provider.isActive)
        assertEquals(6, provider.modelsCount)
        assertTrue(provider.apiKeyConfigured)
    }

    @Test
    fun modelInfoDecodesRealPayloadWithNullContextWindow() {
        val payload = """
            {"model_id":"DeepSeek-V4-Flash-Vision-Exp","name":"Deepseek V4 Flash Vision Exp",
             "provider":"amd","capabilities":["text","vision"],"context_window":null,
             "max_tokens":null,"max_output_tokens":262144,"is_active":false,
             "status":"available","connectable":true}
        """.trimIndent()
        val model = json.decodeFromString(ModelInfo.serializer(), payload)
        assertEquals("DeepSeek-V4-Flash-Vision-Exp", model.modelId)
        assertEquals("amd", model.provider)
        assertTrue(model.capabilities.contains("vision"))
        assertNull("实测 context_window 为 null，必须可空", model.contextWindow)
        assertNull(model.maxTokens)
        assertFalse(model.isActive)
    }

    @Test
    fun adminUserListDecodesRealPayload() {
        val payload = """
            {"items":[{"id":3,"username":"admin","email":"admin@neurova.local",
             "role":"admin","active":true,"created_at":"2026-10-24 14:09:11","last_login":""}],
             "total":1}
        """.trimIndent()
        val list = json.decodeFromString(AdminUserList.serializer(), payload)
        assertEquals(1, list.total)
        assertEquals("admin", list.items[0].username)
        assertEquals("admin", list.items[0].role)
        assertTrue(list.items[0].active)
    }

    @Test
    fun adminGroupDecodesRealPayload() {
        val payload = """
            {"group_id":"super_admin","name":"超级管理员","description":"拥有系统所有权限的超级管理员组",
             "owner_id":"","members":[],"members_count":0,"allowed_modules":[],"is_system":true,
             "created_at":1794755895.682005,"updated_at":1794755895.682005,
             "parent_group_id":null,"allowed_categories":[],"default_category":null}
        """.trimIndent()
        val group = json.decodeFromString(AdminGroup.serializer(), payload)
        assertEquals("super_admin", group.groupId)
        assertEquals("超级管理员", group.name)
        assertEquals(0, group.membersCount)
    }

    @Test
    fun providerAndModelListsDecodeBareArrays() {
        val providers = json.decodeFromJsonElement(
            ListSerializer(ProviderInfo.serializer()),
            json.parseToJsonElement("""[{"provider_id":"p1","name":"P1","provider_type":"openai","base_url":"http://x","is_active":true,"status":"unknown","models_count":1,"health":"unknown","api_key_configured":false}]"""),
        )
        assertEquals(1, providers.size)
        val models = json.decodeFromJsonElement(
            ListSerializer(ModelInfo.serializer()),
            json.parseToJsonElement("""[{"model_id":"m1","name":"M1","provider":"p1","capabilities":[],"context_window":null,"max_tokens":null,"is_active":true,"status":"available"}]"""),
        )
        assertEquals("m1", models[0].modelId)
    }
}
