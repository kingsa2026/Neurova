package top.neurova.mobile.feature.knowledge

import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import top.neurova.mobile.core.model.KnowledgeEntry
import top.neurova.mobile.core.model.KnowledgeListPayload
import top.neurova.mobile.core.net.HttpChannel

/**
 * 知识域仓库（F9 轻量子集；端点与 PC/鸿蒙同源，knowledge_core.py + knowledge_sharing.py）：
 *   GET  /knowledge?page=&page_size=   分页列表（信封 data:{items,total,page,page_size}）
 *   POST /knowledge/search {query,limit} → 裸数组 [item_response]
 */
class KnowledgeRepository(private val http: HttpChannel) {

    private val json = Json { ignoreUnknownKeys = true }

    suspend fun list(page: Int = 1, pageSize: Int = 20): KnowledgeListPayload {
        val data = http.unwrapData(
            http.getJson("/knowledge", mapOf("page" to page.toString(), "page_size" to pageSize.toString())),
        )
        return json.decodeFromJsonElement(KnowledgeListPayload.serializer(), data)
    }

    suspend fun search(query: String, limit: Int = 30): List<KnowledgeEntry> {
        val body = JsonObject(
            mapOf("query" to JsonPrimitive(query), "limit" to JsonPrimitive(limit)),
        )
        val bare = http.unwrapData(http.postJson("/knowledge/search", body))
        return json.decodeFromJsonElement(ListSerializer(KnowledgeEntry.serializer()), bare)
    }
}
