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
  // 详情面独有：列表面不夹带运行明细（与"列表不夹带正文"同一口径）。
  evolution_run?: EvolutionRunAudit | null
  evolution_run_status?: AuditRunState
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
