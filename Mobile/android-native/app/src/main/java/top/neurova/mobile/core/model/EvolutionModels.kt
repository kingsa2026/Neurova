package top.neurova.mobile.core.model

import kotlinx.serialization.Serializable

/**
 * 演化状态域模型（P1-8 只读面；端点与 PC/鸿蒙同源）：
 *   GET /governance/rsi/generations?limit=&status= → {code,data:{generations:[摘要],count}}
 *   GET /governance/rsi/generations/current        → {code,data:世代全档}（尚无部署 404）
 *   GET /governance/rsi/generations/{no}           → {code,data:世代全档}
 *   GET /governance/rsi/generations/{no}/lineage   → {code,data:{lineage:[...]}}
 * 字段名对齐后端 generation_ledger.py `EvolutionGeneration.to_dict()`，
 * 前端不另立一套解释。
 */

/** 门禁三态结论（GateVerdict：passed / failed / unevidenced） */
@Serializable
data class EvolutionVerdict(
    val state: String = "",
    val reason: String = "",
)

/** 裁决引用（DecisionRef：auto / approval(approver) / rejected(reason)） */
@Serializable
data class EvolutionDecision(
    val kind: String = "",
    val approver: String = "",
    val reason: String = "",
)

/** 部署引用（DeploymentRef：金丝雀结论 / 晋升时刻 / 回滚落点） */
@Serializable
data class EvolutionDeployment(
    val promotedAt: String = "",
    val canaryConclusion: String = "",
    val rolledBackTo: Long? = null,
    val canaryStartedAt: String = "",
)

/** 信号引用（SignalRef：为什么改） */
@Serializable
data class EvolutionSignal(
    val kind: String = "",
    val ref: String = "",
    val summary: String = "",
)

/** 变更引用（ChangeRef：改了什么） */
@Serializable
data class EvolutionChange(
    val targetId: String = "",
    val kind: String = "",
    val ref: String = "",
    val rationale: String = "",
)

/** 世代全档（详情面出街；verdicts 键为 g0..g4 等门禁名） */
@Serializable
data class EvolutionGeneration(
    val generationNo: Long,
    val parentNo: Long? = null,
    val basisCommit: String = "",
    val createdAt: String = "",
    val signals: List<EvolutionSignal> = emptyList(),
    val changes: List<EvolutionChange> = emptyList(),
    val verdicts: Map<String, EvolutionVerdict> = emptyMap(),
    val decision: EvolutionDecision? = null,
    val deployment: EvolutionDeployment? = null,
    val status: String = "",
)

/** 列表条目（governance.py _generationSummary：只出摘要字段） */
@Serializable
data class EvolutionGenerationSummary(
    val generationNo: Long,
    val parentNo: Long? = null,
    val status: String = "",
    val decision: EvolutionDecision? = null,
    val promotedAt: String = "",
)

/** 世代列表载荷 */
@Serializable
data class EvolutionGenerationList(
    val generations: List<EvolutionGenerationSummary> = emptyList(),
    val count: Int = 0,
)

/** 谱系链载荷 */
@Serializable
data class EvolutionLineage(
    val lineage: List<EvolutionGeneration> = emptyList(),
)
