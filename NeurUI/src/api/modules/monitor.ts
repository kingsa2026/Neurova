import api from '@/api'

// ---------------------------------------------------------------------------
// Monitor API（P2-33：自 MonitorPage 裸写 URL 收编进 api modules）
// ---------------------------------------------------------------------------

const BASE = '/monitor'

/** 系统资源读数（CPU/内存/磁盘等）。 */
export function getMonitorResources() {
  return api.get(`${BASE}/resources`)
}

/** 活动连接读数。 */
export function getMonitorConnections() {
  return api.get(`${BASE}/connections`)
}

/** 告警列表。 */
export function getMonitorAlerts() {
  return api.get(`${BASE}/alerts`)
}

/** 确认（解决）一条告警。 */
export function resolveMonitorAlert(alertId: string) {
  return api.post(`${BASE}/alerts/${encodeURIComponent(alertId)}/resolve`)
}
