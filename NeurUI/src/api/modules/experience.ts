import api from '@/api'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ExperienceRecord {
  id: string
  agent_id: string
  task_type: string
  skill_name?: string
  context: string
  outcome: 'success' | 'failure' | 'partial'
  success_rate?: number
  experience_count?: number
  proficiency?: number
  lessons?: string[]
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
