import { request } from '@/api'

export type SleepStage = 'active' | 'light' | 'rem' | 'deep'

export interface SleepStatus {
  agent_id: string
  stage: SleepStage
  stage_name: string
  start_time: string
  duration_seconds: number
  brainwave_pattern: string
  idle_time?: number
  next_phase?: string
  sleep_mode?: string
}

export interface SleepSettings {
  agent_id: string
  idle_to_light_minutes: number
  light_to_rem_minutes: number
  rem_to_deep_minutes: number
  memory_merge_threshold: number
  conflict_resolution: 'latest' | 'count' | 'consensus' | 'importance'
  auto_cleanup_enabled: boolean
  max_dream_logs: number
  dream_analysis_enabled: boolean
  memory_consolidation_enabled: boolean
  sleep_schedule: {
    enabled: boolean
    sleep_time: string
    wake_time: string
  }
  updated_at?: string
}

export interface DreamLog {
  id: string
  agent_id: string
  content: string
  tags: string[]
  created_at: string
  emotional_valence: number
  is_lucid: boolean
}

export interface DreamLogListResponse {
  items: DreamLog[]
  total: number
  page: number
  page_size: number
}

export interface DreamInsight {
  id: string
  agent_id: string
  type: 'pattern' | 'theme' | 'suggestion' | 'summary'
  title: string
  content: string
  related_dream_ids: string[]
  created_at: string
}

export interface DreamInsightListResponse {
  items: DreamInsight[]
  total: number
  page: number
  page_size: number
}

export interface MemoryMerge {
  id: string
  agent_id: string
  merged_memory_ids: string[]
  result_memory_id: string
  similarity_score: number
  merged_at: string
}

export interface MemoryMergeListResponse {
  items: MemoryMerge[]
  total: number
  page: number
  page_size: number
}

export interface ConflictResolution {
  id: string
  agent_id: string
  conflicting_memory_ids: string[]
  resolution_method: string
  winning_memory_id: string
  resolved_at: string
}

export interface ConflictResolutionListResponse {
  items: ConflictResolution[]
  total: number
  page: number
  page_size: number
}

export const sleepAPI = {
  getStatus: (agentId: string) =>
    request.get<SleepStatus>(`/agents/${agentId}/sleep/status`),

  getSettings: (agentId: string) =>
    request.get<SleepSettings>(`/agents/${agentId}/sleep/settings`),

  updateSettings: (agentId: string, data: Partial<SleepSettings>) =>
    request.put<SleepSettings>(`/agents/${agentId}/sleep/settings`, data),

  getDreamLogs: (agentId: string, params?: { limit?: number; offset?: number }) =>
    request.get<DreamLogListResponse>(`/agents/${agentId}/sleep/dreams`, { params }),

  getDreamLog: (agentId: string, dreamId: string) =>
    request.get<DreamLog>(`/agents/${agentId}/sleep/dreams/${dreamId}`),

  getDreamInsights: (agentId: string, params?: { limit?: number; offset?: number }) =>
    request.get<DreamInsightListResponse>(`/agents/${agentId}/sleep/insights`, { params }),

  getDreamInsight: (agentId: string, insightId: string) =>
    request.get<DreamInsight>(`/agents/${agentId}/sleep/insights/${insightId}`),

  getMemoryMerges: (agentId: string, params?: { limit?: number; offset?: number }) =>
    request.get<MemoryMergeListResponse>(`/agents/${agentId}/sleep/merges`, { params }),

  getMemoryMerge: (agentId: string, mergeId: string) =>
    request.get<MemoryMerge>(`/agents/${agentId}/sleep/merges/${mergeId}`),

  getConflictResolutions: (agentId: string, params?: { limit?: number; offset?: number }) =>
    request.get<ConflictResolutionListResponse>(`/agents/${agentId}/sleep/conflicts`, { params }),

  getConflictResolution: (agentId: string, conflictId: string) =>
    request.get<ConflictResolution>(`/agents/${agentId}/sleep/conflicts/${conflictId}`),

  wakeUp: (agentId: string) =>
    request.post<{ success: boolean }>(`/agents/${agentId}/sleep/wake`),

  startSleep: (agentId: string, targetStage?: SleepStage) =>
    request.post<{ success: boolean }>(`/agents/${agentId}/sleep/start`, { target_stage: targetStage }),
}
