package top.neurova.mobile.feature.models

import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import top.neurova.mobile.core.model.ActiveModel
import top.neurova.mobile.core.model.CheckConnectionResult
import top.neurova.mobile.core.model.ModelInfo
import top.neurova.mobile.core.model.ProviderInfo
import top.neurova.mobile.core.net.HttpChannel

/**
 * 模型域仓库（P8 模型管理页；端点与 PC/鸿蒙同源，provider.py + model.py 事实源）：
 *   GET  /providers、/models                裸数组
 *   GET  /providers/active-model            当前激活模型
 *   POST /providers/{id}/check-connection   连通性探测
 */
class ModelsRepository(private val http: HttpChannel) {

    private val json = Json { ignoreUnknownKeys = true }

    suspend fun providers(): List<ProviderInfo> {
        val bare = http.unwrapData(http.getJson("/providers"))
        return json.decodeFromJsonElement(ListSerializer(ProviderInfo.serializer()), bare)
    }

    suspend fun models(): List<ModelInfo> {
        val bare = http.unwrapData(http.getJson("/models"))
        return json.decodeFromJsonElement(ListSerializer(ModelInfo.serializer()), bare)
    }

    suspend fun activeModel(): ActiveModel {
        val data = http.unwrapData(http.getJson("/providers/active-model"))
        return json.decodeFromJsonElement(ActiveModel.serializer(), data)
    }

    suspend fun checkConnection(providerId: String): CheckConnectionResult {
        val data = http.unwrapData(
            http.postJson("/providers/$providerId/check-connection", JsonObject(emptyMap())),
        )
        return json.decodeFromJsonElement(CheckConnectionResult.serializer(), data)
    }

    /** 激活模型（管理员操作；UI 在 P8 仅管理员域入口暴露） */
    suspend fun activateModel(providerId: String, modelId: String) {
        http.postJson(
            "/providers/activate-model",
            JsonObject(
                mapOf(
                    "provider_id" to JsonPrimitive(providerId),
                    "model_id" to JsonPrimitive(modelId),
                ),
            ),
        )
    }

    /** 新增服务商（POST /providers，CreateProviderRequest；空值字段不下发） */
    suspend fun createProvider(name: String, providerType: String, baseUrl: String, apiKey: String) {
        val body = buildMap {
            put("name", JsonPrimitive(name))
            put("provider_type", JsonPrimitive(providerType))
            if (baseUrl.isNotBlank()) put("base_url", JsonPrimitive(baseUrl))
            if (apiKey.isNotBlank()) put("api_key", JsonPrimitive(apiKey))
        }
        http.postJson("/providers", JsonObject(body))
    }

    /** 更新服务商（PUT /providers/{id}，UpdateProviderRequest；null=不改动该字段） */
    suspend fun updateProvider(providerId: String, name: String?, baseUrl: String?, apiKey: String?) {
        val body = buildMap {
            name?.takeIf { it.isNotBlank() }?.let { put("name", JsonPrimitive(it)) }
            baseUrl?.let { put("base_url", JsonPrimitive(it)) }
            apiKey?.takeIf { it.isNotBlank() }?.let { put("api_key", JsonPrimitive(it)) }
        }
        http.putJson("/providers/$providerId", JsonObject(body))
    }

    /** 删除服务商（DELETE /providers/{id}） */
    suspend fun deleteProvider(providerId: String) {
        http.deleteJson("/providers/$providerId")
    }
}
