import { request } from '@/api'

import type { ScheduleConfig, TaskRequest, RetryPolicy, NotificationConfig, TaskDependency, UnknownRecord } from '@/types/api'

export interface TaskCreateRequest {
  name: string
  description?: string
  type?: string
  enabled?: boolean
  priority?: string
  schedule?: ScheduleConfig
  request?: TaskRequest
  dependencies?: TaskDependency[]
  retry_policy?: RetryPolicy
  notifications?: NotificationConfig
  max_execution_time?: number
  tags?: string[]
  created_by?: string
}

export interface TaskUpdateRequest {
  name?: string
  description?: string
  type?: string
  enabled?: boolean
  priority?: string
  schedule?: ScheduleConfig
  request?: TaskRequest
  dependencies?: TaskDependency[]
  retry_policy?: RetryPolicy
  notifications?: NotificationConfig
  max_execution_time?: number
  tags?: string[]
}

export interface ExecuteRequest {
  input?: UnknownRecord
}

export interface DependencyRequest {
  task_id: string
  type?: string
}

export interface CronValidateRequest {
  cron: string
  timezone?: string
}

export interface NextRunsRequest {
  cron: string
  timezone?: string
  count?: number
}

export const schedulerAPI = {
  listTasks: (params?: { page?: number; page_size?: number; type?: string; enabled?: boolean; search?: string }) =>
    request.get('/scheduler/tasks', { params }),
  createTask: (data: TaskCreateRequest) =>
    request.post('/scheduler/tasks', data),
  getTask: (id: string) =>
    request.get(`/scheduler/tasks/${id}`),
  updateTask: (id: string, data: TaskUpdateRequest) =>
    request.put(`/scheduler/tasks/${id}`, data),
  deleteTask: (id: string) =>
    request.delete(`/scheduler/tasks/${id}`),
  batchDeleteTasks: (taskIds: string[]) =>
    request.post('/scheduler/tasks/batch-delete', null, { params: { task_ids: taskIds.join(',') } }),

  enableTask: (id: string) =>
    request.post(`/scheduler/tasks/${id}/enable`),
  disableTask: (id: string) =>
    request.post(`/scheduler/tasks/${id}/disable`),
  executeTask: (id: string, data: ExecuteRequest = {}) =>
    request.post(`/scheduler/tasks/${id}/execute`, data),
  cancelExecution: (id: string, executionId: string) =>
    request.post(`/scheduler/tasks/${id}/executions/${executionId}/cancel`),

  addDependency: (id: string, data: DependencyRequest) =>
    request.post(`/scheduler/tasks/${id}/dependencies`, data),
  removeDependency: (id: string, dependencyTaskId: string) =>
    request.delete(`/scheduler/tasks/${id}/dependencies/${dependencyTaskId}`),
  getDependencyGraph: () =>
    request.get('/scheduler/dependencies/graph'),

  getExecutionHistory: (id: string, params?: { page?: number; page_size?: number; status?: string }) =>
    request.get(`/scheduler/tasks/${id}/executions`, { params }),
  getExecutionDetail: (id: string, executionId: string) =>
    request.get(`/scheduler/tasks/${id}/executions/${executionId}`),
  getExecutionLogs: (id: string, executionId: string) =>
    request.get(`/scheduler/tasks/${id}/executions/${executionId}/logs`),
  getAllExecutions: (params?: { page?: number; page_size?: number; status?: string; task_type?: string }) =>
    request.get('/scheduler/executions', { params }),

  getTaskStats: (id: string) =>
    request.get(`/scheduler/tasks/${id}/stats`),
  getOverviewStats: () =>
    request.get('/scheduler/stats/overview'),

  validateCron: (data: CronValidateRequest) =>
    request.post('/scheduler/cron/validate', data),
  getNextRuns: (data: NextRunsRequest) =>
    request.post('/scheduler/cron/next-runs', data),

  exportTasks: (taskIds?: string[]) =>
    request.post('/scheduler/tasks/export', null, { params: taskIds ? { task_ids: taskIds.join(',') } : undefined }),
  importTasks: (tasksData: unknown[]) =>
    request.post('/scheduler/tasks/import', tasksData),
}
