package top.neurova.mobile.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** 知识条目（GET /knowledge 的 item_response，knowledge_core.py 事实源；content 为长文本，UI 只展示元信息） */
@Serializable
data class KnowledgeEntry(
    @SerialName("knowledge_id") val knowledgeId: String,
    val title: String = "",
    val content: String = "",
    val category: String = "",
    val tags: List<String> = emptyList(),
    val source: String = "",
    val confidence: Double = 0.0,
    // 后端时间是浮点秒（实测 1791279148.074471），Long 会解码失败
    @SerialName("created_at") val createdAt: Double? = null,
    @SerialName("updated_at") val updatedAt: Double? = null,
    val visibility: String = "",
    @SerialName("owner_user_id") val ownerUserId: String? = null,
    @SerialName("shared_with") val sharedWith: List<String> = emptyList(),
)

/** GET /knowledge 信封 data 载荷 */
@Serializable
data class KnowledgeListPayload(
    val items: List<KnowledgeEntry> = emptyList(),
    val total: Int = 0,
    val page: Int = 1,
    @SerialName("page_size") val pageSize: Int = 20,
)
