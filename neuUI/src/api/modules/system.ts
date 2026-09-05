import { request } from '@/api'

export const systemAPI = {
  getHealth: () => request.get('/health'),
  getHealthChecks: () => request.get('/health/checks'),
  getHealthReport: () => request.get('/health/report'),
  runHealthCheck: (checkName: string) => request.post(`/health/checks/${checkName}/run`),
  triggerRecovery: () => request.post('/health/recover'),
  getLogs: (params?: Record<string, unknown>) => request.get('/logs', { params }),
  getNotifications: () => request.get('/notifications'),
  getStats: () => request.get('/stats/system'),
  getAnalytics: () => request.get('/analytics'),
}
