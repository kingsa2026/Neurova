package top.neurova.mobile.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** 服务商（GET /providers 裸数组；provider.py ProviderInfo 投影） */
@Serializable
data class ProviderInfo(
    @SerialName("provider_id") val providerId: String,
    val name: String = "",
    @SerialName("provider_type") val providerType: String = "",
    @SerialName("base_url") val baseUrl: String = "",
    @SerialName("is_active") val isActive: Boolean = false,
    val status: String = "",
    @SerialName("models_count") val modelsCount: Int = 0,
    val health: String = "",
    @SerialName("api_key_configured") val apiKeyConfigured: Boolean = false,
)

/** 模型（GET /models 裸数组；model.py ModelInfo 投影子集；context_window/max_tokens 实测可 null） */
@Serializable
data class ModelInfo(
    @SerialName("model_id") val modelId: String,
    val name: String = "",
    val provider: String = "",
    val capabilities: List<String> = emptyList(),
    @SerialName("context_window") val contextWindow: Long? = null,
    @SerialName("max_tokens") val maxTokens: Long? = null,
    @SerialName("is_active") val isActive: Boolean = false,
    val status: String = "",
)

/** 活跃模型（GET /providers/active-model 的 data） */
@Serializable
data class ActiveModel(
    val model: String? = null,
    val provider: String? = null,
)

/** 连通性探测（POST /providers/{id}/check-connection 的 data） */
@Serializable
data class CheckConnectionResult(
    val connected: Boolean = false,
    val message: String = "",
)

/** 管理员用户（GET /enhanced-users 的 items 元素） */
@Serializable
data class AdminUser(
    val id: Long,
    val username: String = "",
    val email: String = "",
    val role: String = "",
    val active: Boolean = false,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("last_login") val lastLogin: String? = null,
)

/** GET /enhanced-users 裸载荷 {items,total} */
@Serializable
data class AdminUserList(
    val items: List<AdminUser> = emptyList(),
    val total: Int = 0,
)

/** 用户组（GET /groups 裸数组；groups_api GroupInfo 投影） */
@Serializable
data class AdminGroup(
    @SerialName("group_id") val groupId: String,
    val name: String = "",
    val description: String = "",
    @SerialName("owner_id") val ownerId: String? = null,
    val members: List<String> = emptyList(),
    @SerialName("members_count") val membersCount: Int = 0,
)
