import api from '@/api'

// ---------------------------------------------------------------------------
// Monitor API（P2-33：自 MonitorPage 裸写 URL 收编进 api modules）
// ---------------------------------------------------------------------------

const BASE = '/monitor'

/**
 * S2 子代理邮箱运维快照（/monitor/resources 响应的 mailbox 字段）。
 *
 * 与后端 neurova/agent/mailbox.py stats() 快照键集逐字对齐：
 * 在途租约/待就绪/ACK 累计/回收累计/去重累计/会话数/优先级分布。
 * 后端 fail-soft：邮箱不可用时该字段为 null（资源读数不受拖累）。
 */
export interface MonitorMailboxStats {
  sessions?: number
  pendingTotal?: number
  readyTotal?: number
  leasedTotal?: number
  ackedTotal?: number
  reclaimedTotal?: number
  dedupedTotal?: number
  priorityDistribution?: { normal?: number; high?: number; urgent?: number }
}

/** /monitor/resources 响应 data（前端嵌套契约：cpu/memory/disk 各为对象）。 */
export interface MonitorResourcesData {
  cpu?: Record<string, unknown>
  memory?: Record<string, unknown>
  disk?: Record<string, unknown>
  mailbox?: MonitorMailboxStats | null
}

/** 系统资源读数（CPU/内存/磁盘；S2 起含 mailbox 邮箱快照，fail-soft 可空）。 */
export function getMonitorResources() {
  return api.get<{ data: MonitorResourcesData }>(`${BASE}/resources`)
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
