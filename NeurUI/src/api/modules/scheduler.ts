import api from '@/api'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ScheduledTask {
  id: string
  name: string
  description?: string
  cron_expr: string
  agent_id?: string
  action: string
  payload?: Record<string, unknown>
  enabled: boolean
  last_run?: string
  next_run?: string
  status: 'idle' | 'running' | 'error'
  created_at: string
  updated_at?: string
}

export interface TaskCreatePayload {
  name: string
  description?: string
  cron_expr: string
  agent_id?: string
  action: string
  payload?: Record<string, unknown>
  enabled?: boolean
}

export interface SchedulerStatus {
  running: boolean
  total_tasks: number
  active_tasks: number
  uptime_seconds: number
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/scheduler'

/** Get scheduler daemon status. */
export function getSchedulerStatus() {
  return api.get<ApiResponse<SchedulerStatus>>(`${BASE}/status`)
}

/** List scheduled tasks. */
export function getScheduledTasks(params?: PageParams & { agent_id?: string; enabled?: boolean }) {
  return api.get<ApiResponse<PaginatedData<ScheduledTask>>>(`${BASE}/tasks`, { params })
}

/** Get a single scheduled task. */
export function getScheduledTask(id: string) {
  return api.get<ApiResponse<ScheduledTask>>(`${BASE}/tasks/${id}`)
}

/** Create a scheduled task. */
export function createScheduledTask(data: TaskCreatePayload) {
  return api.post<ApiResponse<ScheduledTask>>(`${BASE}/tasks`, data)
}

/** Update a scheduled task. */
export function updateScheduledTask(id: string, data: Partial<TaskCreatePayload>) {
  return api.put<ApiResponse<ScheduledTask>>(`${BASE}/tasks/${id}`, data)
}

/** Delete a scheduled task. */
export function deleteScheduledTask(id: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/tasks/${id}`)
}
