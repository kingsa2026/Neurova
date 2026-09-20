import api from '@/api'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** 人工处置态（工单 015）；null = 未处置/已恢复 */
export type ExperienceDisposition = 'endorsed' | 'demoted' | 'suppressed'

export interface ExperienceRecord {
  id: string
  agent_id: string
  task_type: string
  skill_name?: string
  context: string
  outcome: 'success' | 'failure' | 'partial'
  /** 置信度；后端无该值时给 null，不再回落成 1/0 二值（工单 015） */
  success_rate?: number | null
  proficiency?: number | null
  /** 同一 (agent, skill) 的真实条数（后端曾硬编码 1） */
  experience_count?: number
  lessons?: string[]
  /** 采纳后证据（工单 006 回写）；null = 从未回写 */
  adoption_outcome?: 'success' | 'failure' | 'unevidenced' | null
  /** 形成侧证据态（工单 008） */
  evidence_state?: 'evidenced' | 'unevidenced' | null
  injected_count?: number
  seen_count?: number
  operator_disposition?: ExperienceDisposition | null
  metadata?: Record<string, unknown>
  created_at: string
  updated_at?: string
}

export interface ExperienceCreatePayload {
  agent_id: string
  task_type: string
  context: string
  outcome: string
  lessons?: string[]
  metadata?: Record<string, unknown>
}

export interface ExperienceStats {
  total_experiences: number
  success_rate: number
  avg_proficiency: number
  top_categories: { category: string; count: number }[]
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/experience'

/** List experience records for an agent (uses /ranking endpoint). */
export function getExperiences(agentId: string, params?: PageParams & { task_type?: string }) {
  return api.get<ApiResponse<PaginatedData<ExperienceRecord>>>(`${BASE}/ranking`, { params: { ...params, agent_id: agentId } })
}

/** Get a single experience record. */
export function getExperience(id: string) {
  return api.get<ApiResponse<ExperienceRecord>>(`${BASE}/${id}`)
}

/** Create a new experience record. */
export function createExperience(data: ExperienceCreatePayload) {
  return api.post<ApiResponse<ExperienceRecord>>(`${BASE}/records`, data)
}

/** Delete an experience record. */
export function deleteExperience(id: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/${id}`)
}

/**
 * 人工处置一条经验（工单 015）：审核通过 / 降权 / 隐藏；null = 恢复未处置。
 *
 * 处置与删除是两件事：这里全程可逆、不删数据。降权会真的改写检索排序与注入
 * 优先级（后端 `find_similar_experiences` / `dedupe_experience_sources`），
 * 不是只改界面态。
 */
export function setExperienceDisposition(id: string, disposition: ExperienceDisposition | null) {
  return api.put<ApiResponse<ExperienceRecord>>(`${BASE}/${id}/disposition`, { disposition })
}

/** Search for similar experiences. */
export function searchSimilar(agentId: string, query: string, limit = 5) {
  return api.post<ApiResponse<ExperienceRecord[]>>(`${BASE}/similar`, { agent_id: agentId, query, limit })
}

/** Get experience recommendations for a task (uses /ranking as fallback). */
export function getRecommendations(agentId: string, taskType: string, limit = 5) {
  return api.get<ApiResponse<PaginatedData<ExperienceRecord>>>(`${BASE}/ranking`, { params: { agent_id: agentId, task_type: taskType, limit } })
}

/** Get experience statistics for an agent. */
export function getExperienceStats(agentId: string) {
  return api.get<ApiResponse<ExperienceStats>>(`${BASE}/stats`, { params: { agent_id: agentId } })
}

/** Get experience ranking. */
export function getExperienceRanking(agentId: string, params?: PageParams) {
  return api.get<ApiResponse<PaginatedData<ExperienceRecord>>>(`${BASE}/ranking`, { params: { ...params, agent_id: agentId } })
}
