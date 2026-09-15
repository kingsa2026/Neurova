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

export interface EvolutionProposal {
  proposal_id: string
  skill_id: string
  artifact_type: string
  status: 'pending' | 'approved' | 'rejected' | string
  holdout_before: number
  holdout_after: number
  iterations_run: number
  created_at: string
  decided_at: string
  baseline_text?: string
  improved_text?: string
}

export type ProposalSummary = Omit<EvolutionProposal, 'baseline_text' | 'improved_text'>

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
