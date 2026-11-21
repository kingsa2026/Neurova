package top.neurova.mobile.feature.admin

import kotlinx.serialization.json.Json
import top.neurova.mobile.core.model.EvolutionGeneration
import top.neurova.mobile.core.model.EvolutionGenerationList
import top.neurova.mobile.core.model.EvolutionLineage
import top.neurova.mobile.core.net.HttpChannel

/**
 * 演化状态域仓库（P1-8 只读面；端点与 PC/鸿蒙同源，均 admin 门）：
 *   GET /governance/rsi/generations?limit=&status=  世代列表（摘要）
 *   GET /governance/rsi/generations/current         当前生产基线代
 *   GET /governance/rsi/generations/{no}            单代详情
 *   GET /governance/rsi/generations/{no}/lineage    谱系回溯链
 * 非 2xx 状态（404 无基线代 / 503 管线未装配）由 HttpChannel 抛
 * ChannelHttpException（detail 已抽出原因），屏幕层按原因诚实呈现。
 */
class EvolutionRepository(private val http: HttpChannel) {

    private val json = Json { ignoreUnknownKeys = true }

    /** 世代列表（limit 截取最近 N 代；status 可选过滤；空账本 → 空列表） */
    suspend fun generations(limit: Int = 10, status: String? = null): EvolutionGenerationList {
        val query = if (status.isNullOrBlank()) {
            mapOf("limit" to limit.toString())
        } else {
            mapOf("limit" to limit.toString(), "status" to status)
        }
        val bare = http.unwrapData(http.getJson("/governance/rsi/generations", query))
        return json.decodeFromJsonElement(EvolutionGenerationList.serializer(), bare)
    }

    /** 当前生产基线代（序号最大的 deployed 代；尚无部署后端 404） */
    suspend fun currentBaseline(): EvolutionGeneration {
        val bare = http.unwrapData(http.getJson("/governance/rsi/generations/current"))
        return json.decodeFromJsonElement(EvolutionGeneration.serializer(), bare)
    }

    /** 单代详情（signals/changes/verdicts 全量/decision/deployment） */
    suspend fun generationDetail(generationNo: Long): EvolutionGeneration {
        val bare = http.unwrapData(http.getJson("/governance/rsi/generations/$generationNo"))
        return json.decodeFromJsonElement(EvolutionGeneration.serializer(), bare)
    }

    /** 谱系回溯链（从指定代沿 parentNo 向上到根代，含自身） */
    suspend fun lineage(generationNo: Long): EvolutionLineage {
        val bare = http.unwrapData(http.getJson("/governance/rsi/generations/$generationNo/lineage"))
        return json.decodeFromJsonElement(EvolutionLineage.serializer(), bare)
    }
}
