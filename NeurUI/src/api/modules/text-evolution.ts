import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types — 文本进化与技能生命周期
// 读 = 登录用户；写（设置/扫描/钉住/进化/审批）= 管理员。
// ---------------------------------------------------------------------------

export interface EvolutionSettings {
  text_evolution: boolean
  lifecycle_sweep: boolean
  lifecycle_interval_hours: number
  judge_model: string
  optimizer_model: string
}

export interface SkillLifecycleItem {
  skill_id: string
  state: 'active' | 'stale' | 'archived' | string
  pinned: boolean
  created_by: string
  use_count: number
  last_activity_at_ms: number
}

export interface LifecycleUsageSummary {
  counts: Record<string, number>
  skills: SkillLifecycleItem[]
}

export interface SweepCounts {
  checked: number
  marked_stale: number
  archived: number
  reactivated: number
  seeded: number
}

export interface EvolutionRunData {
  rejected: boolean
  reject_reason: string
  holdout_before: number
  holdout_after: number
  improvement: number
  train_before: number
  train_best: number
  iterations_run: number
  bench_gain: number
  changed: boolean
  constraint_failures: string[]
  proposal: EvolutionProposal | null
  // 执行面读数：默认 auto 时可能回落模拟面，原因必须可见。
  executor_kind?: string
  executor_requested?: 'auto' | 'real_agent' | 'simulated' | string
  real_trajectory_fallback?: string
  judge_fallback?: string
}

/** 一次进化的审计运行：`runs/*.json` 的内容（§6-95 后半给它接上的读者就是提案详情面）。 */
export interface EvolutionRunAudit {
  run_id: string
  at: string
  skill_id: string
  artifact_type: string
  iterations_run: number
  holdout_before: number
  holdout_after: number
  // False = 判分链全线失败 ⇒ 本轮任何"增益"都不可信，审批人必须看见这句话。
  judge_available: boolean
  // 留出侧逐例读数（线上字段名 `holdout_cases`，与 `EvolutionRunResult.to_dict()` 同形；
  // 不是 dataclass 的字段名 `holdout_case_scores`——写错这里，面板会永远空着）。
  holdout_cases: Record<string, {
    baseline: number
    candidate: number
    baseline_failed?: boolean
    candidate_failed?: boolean
  }>
  // V1 near-miss 修复通道审计：每轮修复尝试（门别/是否改善/证据任务）与
  // 「最终胜者是否由修复通道救回」（V4 归因面）。缺席 = 旧记录或未启用。
  repair_rescued?: boolean
  repair_attempts?: RepairAttempt[]
}

/** V1 单轮修复尝试的审计行（runner.repair_attempts 的出街形态）。 */
export interface RepairAttempt {
  round: number
  gate: string
  improved?: boolean
  blocked?: string
  evidence_tasks?: string[]
  tune_score?: number
}

/** 详情面对那次运行的三态读数；与后端 `SkillEvolutionService.runLookup` 逐字同形。 */
export type AuditRunState = 'attached' | 'missing' | 'none_recorded'

export interface EvolutionProposal {
  proposal_id: string
  skill_id: string
  artifact_type: string
  status: 'pending' | 'applied' | 'rejected' | string
  // 这条提案凭哪一次运行出街（旧记录为空串 = 当轮未记）。
  run_id: string
  holdout_before: number
  holdout_after: number
  iterations_run: number
  created_at: string
  decided_at: string
  baseline_text?: string
  improved_text?: string
  // judge 不可用时的确定性回退提案：自动审批必须拒绝，只能人工复核。
  judge_fallback?: string
  requires_manual_review?: boolean
  // 详情面独有：列表面不夹带运行明细（与"列表不夹带正文"同一口径）。
  evolution_run?: EvolutionRunAudit | null
  evolution_run_status?: AuditRunState
  // ── 证据与代价读数（详情面展示；旧记录整键缺席 ⇒ 空不显示）──
  // M-C：验收证据跑在哪个基座上（空串 = 未记）。
  model_under_test?: string
  // 例级不退化门读数（容忍度/撞坏用例/未量出用例）。
  case_gate?: { allowance: number; regressions: string[]; unevidenced: string[] }
  // 可执行断言面（紧凑出街；逐案明细在 run 审计里）。
  exec_suite?: { state?: string; suite_hash?: string; cases?: number
    baseline_pass_rate?: number | null; candidate_pass_rate?: number | null }
  // B4 judge 选择面 × 密封面增益两列。
  judge_vs_sealed?: { judge_gain?: number; sealed_gain?: number | null; missing?: string[] }
  // 证据的用例来源构成（golden/history/synthetic…）。
  source_mix?: Record<string, number>
  // 成本软门读数（manual_review/within_budget/unmeasured/disabled）。
  cost_gate?: { state: string; ratio?: number; threshold?: number }
  // V6 部署形态成本差：采纳后每任务多花多少（与开发搜索花费分格）。
  deployment_cost?: DeploymentCostDelta
  // V4 增益-代价归因面板。
  gain_attribution?: GainAttribution
  // V3 可进化面读数（本提案改写的是哪个面）。
  surface?: { name: string; label: string; kind: string; max_size: number }
}

/** V6：胜者相对基线臂的每任务执行成本差；unmeasured = 没量到（不是 0）。 */
export interface DeploymentCostDelta {
  state: 'measured' | 'unmeasured' | string
  reason?: string
  baseline_per_case_usd?: number
  candidate_per_case_usd?: number
  delta_per_case_usd?: number
  delta_ratio?: number | null
  baseline_per_case_tokens?: number
  candidate_per_case_tokens?: number
  delta_per_case_tokens?: number
  baseline_cop_usd?: number | null
  candidate_cop_usd?: number | null
}

/** V4：增益-代价归因（数值全部取自运行读数）。 */
export interface GainAttribution {
  surfaces_touched?: string[]
  holdout_gain?: number
  size_delta_ratio?: number | null
  repair_rounds?: number
  repair_rescued?: boolean
  note?: string
}

/** V5 工件里的非劣变体（Pareto 多档交付的档位件）。 */
export interface ArtifactVariant {
  text: string
  score: number
  tier: string
  cost_usd?: number
  tokens?: number
}

/** V5 可部署工件：一次过门运行的版本化交付（冠军＋变体＋证据指针）。 */
export interface EvolutionArtifact {
  artifact_id: string
  skill_id: string
  artifact_type: string
  status: 'pending' | 'applied' | 'rolled_back' | string
  created_at: string
  experiment_fingerprint?: string
  champion_text?: string
  baseline_text?: string
  variants?: ArtifactVariant[]
  evidence?: { run_id?: string; proposal_id?: string; journal_commit?: string | null }
  scores?: Record<string, number | undefined>
  surface?: { name: string; label: string; kind: string; max_size: number }
  cost?: DeploymentCostDelta
}

/** V2 递归演化的分支账本行（branch_pool.EvolutionBranch 的出街形态）。 */
export interface RecursiveBranch {
  branch_id: string
  parent_id: string
  epoch_created: number
  status: 'active' | 'promoted' | 'exhausted' | string
  retries_left: number
  score: number
  promoted_epoch?: number | null
  text_head?: string
}

export type ProposalSummary = Omit<
  EvolutionProposal,
  'baseline_text' | 'improved_text' | 'evolution_run' | 'evolution_run_status'
>

// axios baseURL 已是 config.apiBaseUrl='/api/v1'（全库模块统一不带 /v1 前缀），
// 故此处 BASE 只写资源段；曾误写 '/v1/evolution' 拼成 /api/v1/v1/... 致技能页 usage 404。
const BASE = '/evolution'

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export function getEvolutionSettings() {
  return api.get<ApiResponse<EvolutionSettings>>(`${BASE}/settings`)
}

export function updateEvolutionSettings(patch: Partial<EvolutionSettings>) {
  return api.put<ApiResponse<EvolutionSettings>>(`${BASE}/settings`, patch)
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export function getLifecycleUsage(agentId: string) {
  return api.get<ApiResponse<LifecycleUsageSummary>>(`${BASE}/skills/${agentId}/usage`)
}

export function runLifecycleSweep(agentId: string) {
  return api.post<ApiResponse<SweepCounts>>(`${BASE}/skills/${agentId}/sweep`)
}

export function pinSkill(agentId: string, skillId: string, pinned: boolean) {
  return api.post<ApiResponse<{ pinned: boolean }>>(
    `${BASE}/skills/${agentId}/${skillId}/pin`,
    { pinned },
  )
}

// ---------------------------------------------------------------------------
// Evolution runs & proposals
// ---------------------------------------------------------------------------

export function evolveSkill(
  agentId: string,
  payload: { skill_id: string; iterations?: number; dataset_source?: 'auto' | 'golden' | 'mined' | 'synthetic' },
) {
  return api.post<ApiResponse<EvolutionRunData>>(`${BASE}/skills/${agentId}/evolve`, payload)
}

export function listProposals(agentId: string, status?: string) {
  return api.get<ApiResponse<ProposalSummary[]>>(
    `${BASE}/skills/${agentId}/proposals`,
    { params: status ? { status } : {} },
  )
}

export function getProposal(agentId: string, proposalId: string) {
  return api.get<ApiResponse<EvolutionProposal>>(
    `${BASE}/skills/${agentId}/proposals/${proposalId}`,
  )
}

export function adoptDomainHarness(
  agentId: string,
  peerId: string,
  targetSkillId: string,
) {
  return api.post<ApiResponse<EvolutionProposal>>(
    `${BASE}/skills/${agentId}/domain-harnesses/${peerId}/adopt`,
    { target_skill_id: targetSkillId },
  )
}

export function approveProposal(agentId: string, proposalId: string) {
  return api.post<ApiResponse<{ approved: boolean }>>(
    `${BASE}/skills/${agentId}/proposals/${proposalId}/approve`,
  )
}

export function rejectProposal(agentId: string, proposalId: string) {
  return api.post<ApiResponse<{ rejected: boolean }>>(
    `${BASE}/skills/${agentId}/proposals/${proposalId}/reject`,
  )
}

// ---------------------------------------------------------------------------
// 双臂试评（P1-7b）：同一真留出集上对照基线正文与候选正文，只读评测。
// `executor_kind` 是这一路的**来源标注**：模拟面（单轮 chat，零工具零上下文）与
// 真 agent 轨迹面量的是不同的事，UI 必须分栏显示，不许合并成一个数字。
// ---------------------------------------------------------------------------

export type ArmExecutorKind = 'simulated' | 'real_agent'

export interface AbArmTaskRow {
  task_input: string
  baseline: number
  candidate: number
}

export interface AbReportData {
  task_split: 'heldout' | 'selection' | 'none' | string
  n: number
  baseline_avg: number
  candidate_avg: number
  delta: number
  per_task: AbArmTaskRow[]
  executor_kind: ArmExecutorKind
}

export function abCompareSkills(
  agentId: string,
  payload: {
    skill_id: string
    candidate_text: string
    dataset_source?: 'auto' | 'golden' | 'mined' | 'synthetic'
    real_trajectory?: boolean
  },
) {
  return api.post<ApiResponse<AbReportData>>(`${BASE}/skills/${agentId}/ab`, payload)
}

// ---------------------------------------------------------------------------
// V2 递归多轮演化（分支账本随报告出街）
// ---------------------------------------------------------------------------

export interface RecursiveEpochRow {
  epoch: number
  base_index: number
  branch_id?: string
  parent_id?: string
  rejected: boolean
  reject_reason: string
  holdout_before: number
  holdout_after: number
  improvement: number
  proposal_id?: string
}

export interface RecursiveReport {
  skill_id: string
  baseline_text: string
  deployed_text: string
  epochs_run: number
  epochs: RecursiveEpochRow[]
  pool_size: number
  branch_retries?: number
  branches?: RecursiveBranch[]
  seed_branch_id?: string
  final_pool_size: number
  total_improvement: number
  stopped_reason: string
}

export function evolveSkillRecursive(
  agentId: string,
  payload: {
    skill_id: string
    epochs?: number
    pool_size?: number
    branch_retries?: number
    iterations?: number
    dataset_source?: 'auto' | 'golden' | 'mined' | 'synthetic'
  },
) {
  return api.post<ApiResponse<RecursiveReport>>(
    `${BASE}/skills/${agentId}/evolve-recursive`, payload)
}

// ---------------------------------------------------------------------------
// V5 可部署工件：冠军与非劣变体的版本化交付（列表不夹带正文，详情给全文）
// ---------------------------------------------------------------------------

export function listArtifacts(agentId: string, skillId?: string) {
  return api.get<ApiResponse<EvolutionArtifact[]>>(
    `${BASE}/skills/${agentId}/artifacts`,
    { params: skillId ? { skill_id: skillId } : {} },
  )
}

export function getArtifact(agentId: string, artifactId: string) {
  return api.get<ApiResponse<EvolutionArtifact>>(
    `${BASE}/skills/${agentId}/artifacts/${artifactId}`,
  )
}

export function rollbackArtifact(agentId: string, artifactId: string) {
  return api.post<ApiResponse<{ rolled_back: boolean; skill_id: string }>>(
    `${BASE}/skills/${agentId}/artifacts/${artifactId}/rollback`,
  )
}
