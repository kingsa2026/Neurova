package top.neurova.mobile.feature.admin

import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import top.neurova.mobile.core.model.AdminGroup
import top.neurova.mobile.core.model.AdminUserList
import top.neurova.mobile.core.net.HttpChannel

/**
 * 管理员域仓库（P8 管理员页；端点与 PC/鸿蒙同源）：
 *   GET    /enhanced-users        裸 {items,total}
 *   DELETE /enhanced-users/{id}
 *   GET    /groups                裸数组
 *   POST   /groups                {name,description}
 * 仅 role=admin 可用（UI 侧由路由门控，后端另有鉴权）。
 */
class AdminRepository(private val http: HttpChannel) {

    private val json = Json { ignoreUnknownKeys = true }

    suspend fun users(): AdminUserList {
        val bare = http.unwrapData(http.getJson("/enhanced-users"))
        return json.decodeFromJsonElement(AdminUserList.serializer(), bare)
    }

    suspend fun deleteUser(userId: Long) {
        http.deleteJson("/enhanced-users/$userId")
    }

    suspend fun groups(): List<AdminGroup> {
        val bare = http.unwrapData(http.getJson("/groups"))
        return json.decodeFromJsonElement(ListSerializer(AdminGroup.serializer()), bare)
    }

    suspend fun createGroup(name: String, description: String) {
        http.postJson(
            "/groups",
            JsonObject(
                mapOf(
                    "name" to JsonPrimitive(name),
                    "description" to JsonPrimitive(description),
                ),
            ),
        )
    }
}
