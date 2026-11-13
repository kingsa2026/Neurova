import api from '@/api'
import type { ApiResponse, PageParams } from '@/types/response'

// ---------------------------------------------------------------------------
// Types — 与后端 /v1/scheduler 契约对齐:
//   cron_expression / interval_seconds / parameters / agent_id / task_id
// ---------------------------------------------------------------------------

export interface ScheduledTask {
  task_id: string
  name: string
  description?: string
  cron_expression?: string
  interval_seconds?: number
  scheduled_at?: number
  agent_id?: string
  action: string
  parameters?: Record<string, unknown>
  status: string
  created_at?: number
  updated_at?: number
  last_run_at?: number
  next_run_at?: number
  run_count?: number
}

export interface TaskCreatePayload {
  name: string
  description?: string
  cron_expression?: string
  interval_seconds?: number
  agent_id?: string
  action: string
  parameters?: Record<string, unknown>
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

/** List scheduled tasks. 后端 /tasks 只收 limit（无 offset，P1-13 核对：
 * scheduler.py get_tasks 仅 status/agent_id/limit 三个查询参数），故这里
 * 只透传 limit，不假装支持 offset。 */
export function getScheduledTasks(params?: Pick<PageParams, 'limit'> & { agent_id?: string; status?: string }) {
  const { limit, agent_id, status } = params ?? {}
  return api.get<ApiResponse<ScheduledTask[]>>(`${BASE}/tasks`, { params: { limit, agent_id, status } })
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

/** Run a task immediately (遗留修复: 前端"立即运行"此前为空操作). */
export function runScheduledTask(id: string) {
  return api.post<ApiResponse<Record<string, unknown>>>(`${BASE}/tasks/${id}/run`)
}
