import { request } from '@/api'

export interface AuditLogQuery {
  start_time?: string
  end_time?: string
  event_type?: string
  actor_id?: string
  resource_type?: string
  severity?: string
  success?: boolean
  page?: number
  page_size?: number
}

export const auditAPI = {
  getLogs: (params?: AuditLogQuery) =>
    request.get('/audit/logs', { params }),
  getLog: (logId: number) =>
    request.get(`/audit/logs/${logId}`),
  exportLogs: (params?: {
    format?: 'csv' | 'json'
    start_time?: string
    end_time?: string
    event_type?: string
  }) => request.get('/audit/export', { params }),
  getStatistics: (params?: {
    start_time?: string
    end_time?: string
  }) => request.get('/audit/statistics', { params }),
  getEventTypes: () => request.get('/audit/event-types'),
}
