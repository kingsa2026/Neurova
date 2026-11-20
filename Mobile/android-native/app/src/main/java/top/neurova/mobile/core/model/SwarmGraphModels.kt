package top.neurova.mobile.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * 蜂群协作图投影 DTO（车道G，对齐 PC 端 SwarmFlowPanel.vue / swarmGraph.ts）。
 * 事实源：neurova/agent/swarm_graph_projection.py 与 candidate_projection.py 的 TypedDict；
 * 服务端只出投影、端上只做渲染（P2-4 契约）——本文件只描述投影结构，不做事件语义解释。
 *
 * 命名走后端 snake_case 原文（@SerialName 映射到 camelCase）；epoch 秒与 duration_ms
 * 一律 Double（后端是浮点秒，整型截断会丢毫秒）；全部字段带默认值，后端加字段/减字段
 * 都不炸端上（配合 ignoreUnknownKeys）。
 */

/** 图节点三类同构（nodeType 判别）：run 成员节点 / 审批卡 / 候选卡。 */
@Serializable
data class SwarmGraphNode(
    val id: String = "",
    val nodeType: String = "run",
    @SerialName("run_id") val runId: String = "",
    @SerialName("member_name") val memberName: String = "",
    /** internal | external（仅 run 节点；后端投影对 run 缺省回落 internal，卡节点显式空串） */
    val kind: String = "internal",
    @SerialName("executor_tool") val executorTool: String = "",
    /** run 状态 / 审批裁决态(approved|rejected|pending) / 候选状态 */
    val status: String = "",
    /** 派生深度（0=未知） */
    val depth: Int = 0,
    @SerialName("team_id") val teamId: String = "",
    @SerialName("started_at") val startedAt: Double = 0.0,
    @SerialName("finished_at") val finishedAt: Double = 0.0,
    @SerialName("duration_ms") val durationMs: Double = 0.0,
    @SerialName("error_type") val errorType: String = "",
    /** 审批卡：L0/L1/L2 */
    val level: String = "",
    /** 审批卡：approve/reject */
    val decision: String = "",
    @SerialName("decided_by") val decidedBy: String = "",
    @SerialName("request_id") val requestId: String = "",
    @SerialName("candidate_id") val candidateId: String = "",
    @SerialName("artifact_keys") val artifactKeys: List<String> = emptyList(),
    @SerialName("base_revision") val baseRevision: Int = 0,
    val note: String = "",
)

/** 图边四类（v2 全边集）：spawn | dependency | approval | candidate；"from"/"to" 是字面键。 */
@Serializable
data class SwarmGraphEdge(
    val id: String = "",
    val type: String = "spawn",
    val from: String = "",
    val to: String = "",
    /** 审批边：L0/L1/L2 */
    val level: String = "",
    /** 审批边=裁决态；候选边=候选状态 */
    val status: String = "",
    /** 审批边：approve/reject */
    val decision: String = "",
    @SerialName("decided_by") val decidedBy: String = "",
)

/** 图 meta（诚实标注：截断 / 候选账本缺事件）。 */
@Serializable
data class SwarmGraphMeta(
    val revision: Int = 0,
    @SerialName("generated_at") val generatedAt: Double = 0.0,
    val truncated: Boolean = false,
    @SerialName("candidates_incomplete") val candidatesIncomplete: Boolean = false,
    val counts: Map<String, Int> = emptyMap(),
)

/** 投影本体 {nodes, edges, meta}（信封 data 里还带 parent_session_id，按需取用）。 */
@Serializable
data class SwarmGraphProjection(
    val nodes: List<SwarmGraphNode> = emptyList(),
    val edges: List<SwarmGraphEdge> = emptyList(),
    val meta: SwarmGraphMeta = SwarmGraphMeta(),
)

/** 投影出的单条候选（= 后端 CandidateReport.toDict 去掉 content）。 */
@Serializable
data class SwarmCandidate(
    @SerialName("candidate_id") val candidateId: String = "",
    @SerialName("run_id") val runId: String = "",
    @SerialName("artifact_keys") val artifactKeys: List<String> = emptyList(),
    @SerialName("base_revision") val baseRevision: Int = 0,
    val status: String = "",
    @SerialName("conflict_with") val conflictWith: List<String> = emptyList(),
    val note: String = "",
    /** 重放投影里是 ISO 字符串（区别于图节点的 epoch 秒） */
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("decided_at") val decidedAt: String = "",
)

/** 候选板重放投影快照（incomplete=账本缺事件的诚实标注）。 */
@Serializable
data class SwarmCandidateBoard(
    val revision: Int = 0,
    val candidates: List<SwarmCandidate> = emptyList(),
    val conflicts: List<SwarmCandidate> = emptyList(),
    val incomplete: Boolean = false,
    val source: String = "",
)

/** 节点着色基调（对齐 PC SwarmFlowPanel.vue 的 nf-tone-* 词汇）。 */
enum class SwarmTone {
    RUNNING,
    COMPLETED,
    FAILED,
    WARNING,
}

/**
 * 状态 → 着色基调映射（端上仅有的"词汇翻译"，与 PC 同源同键集）：
 * 未知状态一律落 RUNNING——后端扩态时窗口不渲染成未定义态（LEDGER_TO_WINDOW_STATUS 先例）。
 */
object SwarmStatusTone {

    /** run 节点：台账∪蜂群内存态（RUN_STATUS_TONE 键集）。 */
    fun fromRunStatus(status: String): SwarmTone = when (status) {
        "completed" -> SwarmTone.COMPLETED
        "failed", "cancelled" -> SwarmTone.FAILED
        else -> SwarmTone.RUNNING // queued/pending/parked/running/in_review/未知
    }

    /** 候选状态域四值（CANDIDATE_STATUS_TONE 键集）。 */
    fun fromCandidateStatus(status: String): SwarmTone = when (status) {
        "accepted" -> SwarmTone.COMPLETED
        "rejected" -> SwarmTone.FAILED
        "reviseRequired" -> SwarmTone.WARNING
        else -> SwarmTone.RUNNING // submitted/未知
    }

    /** 审批裁决态（APPROVAL_TONE 键集）。 */
    fun fromApprovalStatus(status: String): SwarmTone = when (status) {
        "approved" -> SwarmTone.COMPLETED
        "rejected" -> SwarmTone.FAILED
        else -> SwarmTone.RUNNING // pending/未知
    }
}
