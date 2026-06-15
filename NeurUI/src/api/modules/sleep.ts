import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SleepStatus {
  agent_id: string
  is_sleeping: boolean
  sleep_phase?: 'light' | 'deep' | 'rem'
  started_at?: string
  duration_seconds?: number
  next_wake?: string
}

export interface SleepSettings {
  agent_id: string
  enabled: boolean
  schedule_start: string
  schedule_end: string
  min_interval_hours: number
  auto_sleep: boolean
  dream_enabled: boolean
}

export interface Dream {
  id: string
  agent_id: string
  content: string
  type: 'consolidation' | 'creative' | 'problem_solving'
  insights?: string[]
  created_at: string
}

export interface SleepInsight {
  id: string
  agent_id: string
  content: string
  source_dream_id?: string
  applied: boolean
  created_at: string
}

export interface MergeConflict {
  id: string
  agent_id: string
  field: string
  local_value: string
  remote_value: string
  resolved: boolean
  resolution?: string
  created_at: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/sleep'

/** Get sleep status for an agent. */
export function getSleepStatus(agentId: string) {
  return api.get<ApiResponse<SleepStatus>>(`${BASE}/${agentId}/status`)
}

/** Get sleep settings. */
export function getSleepSettings(agentId: string) {
  return api.get<ApiResponse<SleepSettings>>(`${BASE}/${agentId}/settings`)
}

/** Update sleep settings. */
export function updateSleepSettings(agentId: string, data: Partial<SleepSettings>) {
  return api.put<ApiResponse<SleepSettings>>(`${BASE}/${agentId}/settings`, data)
}

/** Put agent to sleep. */
export function putToSleep(agentId: string, durationMinutes?: number) {
  return api.post<ApiResponse<null>>(`${BASE}/${agentId}/sleep`, undefined, {
    params: durationMinutes != null ? { duration_minutes: durationMinutes } : undefined,
  })
}

/** Wake agent up. */
export function wakeUp(agentId: string) {
  return api.post<ApiResponse<null>>(`${BASE}/${agentId}/wake`)
}

/** Get dreams list. */
export function getDreams(agentId: string, params?: { limit?: number; offset?: number; type?: string }) {
  return api.get<ApiResponse<{ items: Dream[]; total: number }>>(`${BASE}/${agentId}/dreams`, { params })
}

/** Get sleep insights. */
export function getSleepInsights(agentId: string, params?: { limit?: number; offset?: number }) {
  return api.get<ApiResponse<{ items: SleepInsight[]; total: number }>>(`${BASE}/${agentId}/insights`, { params })
}

/** Apply a sleep insight. */
export function applyInsight(agentId: string, insightId: string) {
  return api.post<ApiResponse<null>>(`${BASE}/${agentId}/insights/${insightId}/apply`)
}

/** Get merge conflicts from sleep consolidation. */
export function getMergeConflicts(agentId: string, params?: { limit?: number; offset?: number; resolved?: boolean }) {
  return api.get<ApiResponse<MergeConflict[]>>(`${BASE}/${agentId}/conflicts`, { params })
}

/** Resolve a merge conflict. */
export function resolveConflict(agentId: string, conflictId: string, resolution: string) {
  return api.post<ApiResponse<null>>(`${BASE}/${agentId}/conflicts/${conflictId}/resolve`, { resolution })
}
