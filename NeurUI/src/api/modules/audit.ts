import api from '@/api'
import { request } from '@/api'
import type { ApiResponse, PaginatedData } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AuditRecord {
  id: string
  timestamp: string
  user: string
  action: string
  resource: string
  details?: Record<string, unknown>
}

export interface AuditStats {
  total: number
  today: number
  warnings: number
}

export interface AuditListParams {
  page?: number
  page_size?: number
  user?: string
  action?: string
  start?: string
  end?: string
}

export interface AuditListResult {
  items: AuditRecord[]
  total: number
  stats: AuditStats
}

/** S8 审批审计事件投影（请求/决定事件的公共形状，与后端 _approval_event_shape 对齐）。 */
export interface ApprovalAuditEvent {
  timestamp?: string
  action?: string
  user_id?: string
  severity?: string
  phase?: string
  request_id?: string
  run_id?: string
  agent_id?: string
  level?: string
  effective_level?: string
  mode?: string
  operation?: string
  reason?: string | null
  decision?: string | null
  decided_by?: string | null
  note?: string | null
  path_values?: Record<string, unknown> | null
  latency_ms?: number | null
}

/** S8 成对轨迹行：一次审批的请求+决定（status=decided|pending）。 */
export interface ApprovalTrajectoryItem {
  request_id: string
  run_id: string
  level?: string | null
  effective_level?: string | null
  operation?: string | null
  reason?: string | null
  mode?: string | null
  status: string
  decision?: string | null
  decided_by?: string | null
  requested_at?: string | null
  decided_at?: string | null
  latency_ms?: number | null
  request_event?: ApprovalAuditEvent | null
  decision_event?: ApprovalAuditEvent | null
}

export interface ApprovalTrajectoryResult {
  run_id: string
  total: number
  requests: ApprovalTrajectoryItem[]
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/audit'

/** List audit records with optional filters. */
export function listAuditRecords(params?: AuditListParams) {
  return api.get<ApiResponse<AuditListResult>>(BASE, { params })
}

/** S8 按 runId 拉取蜂群审批轨迹（请求+决定成对；后端 admin 门，挂既有 audit 查询域）。 */
export function getApprovalTrajectory(runId: string, limit = 50) {
  return api.get<ApiResponse<ApprovalTrajectoryResult>>(`${BASE}/approvals`, {
    params: { run_id: runId, limit },
  })
}

/** Export audit records as JSON blob. */
export function exportAudit(params?: AuditListParams) {
  return request.get(`${BASE}/export`, { params, responseType: 'blob' }) as unknown as Promise<Blob>
}
