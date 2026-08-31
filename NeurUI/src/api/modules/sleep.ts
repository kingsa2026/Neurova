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

// 与后端 neurova/api/endpoints/sleep.py::SleepSettings 严格对齐。
// 此前前端使用 enabled/auto_sleep/dream_enabled 等自造键，后端 Pydantic
// 静默丢弃未知键，设置页读写全部空转。
export interface SleepSettings {
  agent_id: string
  auto_sleep_enabled: boolean
  sleep_threshold_minutes: number
  sleep_duration_minutes: number
  dream_replay_enabled: boolean
  memory_consolidation_enabled: boolean
  conflict_resolution_enabled: boolean
  // 阶段推进参数（"睡多深的节奏"）
  sleep_mode: 'temperature' | 'time' | 'either'
  temp_threshold_light_sleep: number
  temp_threshold_deep_sleep: number
  temp_threshold_rem: number
  temp_threshold_hibernate: number
  idle_threshold_light_sleep: number // 分钟
  idle_threshold_deep_sleep: number
  idle_threshold_rem: number
  idle_threshold_hibernate: number
  monitor_interval_seconds: number
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

/**
 * 睡眠端点解包：/sleep 系列端点返回裸模型/裸数组（无 {code,data} 信封），
 * 而 axios 拦截器已返回响应体本身。此前页面统一按 res?.data 取值导致
 * 读取空转。此 helper 兼容两种形态。
 */
export function unwrapSleep<T = unknown>(res: unknown): T | undefined {
  if (res == null) return undefined
  if (Array.isArray(res)) return res as T
  if (typeof res === 'object' && 'data' in (res as Record<string, unknown>)) {
    return (res as Record<string, unknown>).data as T
  }
  return res as T
}

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
