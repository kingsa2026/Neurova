import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types — 治理中心（白名单 + 审批）
// ---------------------------------------------------------------------------

export interface WhitelistEntry {
  id: string
  pattern: string
  match_type: 'prefix' | 'exact' | 'regex'
  tool?: string | null
  note?: string
  created_at?: string
}

export interface ApprovalRequest {
  request_id: string
  agent_id: string
  user_id: string
  command: string
  description: string
  danger_reason: string
  status: 'pending' | 'approved' | 'rejected' | 'expired' | 'auto_approved'
  created_at: string
  updated_at: string
  expires_at?: string | null
  metadata?: {
    tool_name?: string
    params?: Record<string, unknown>
    governance?: Record<string, unknown>
  }
}

export interface ApproveResult {
  approved: boolean
  executed: boolean
  result?: Record<string, unknown>
  message?: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/governance'

/** 白名单列表 */
export function getWhitelist() {
  return api.get<ApiResponse<{ entries: WhitelistEntry[] }>>(`${BASE}/whitelist`)
}

/** 新增白名单条目 */
export function addWhitelistEntry(entry: {
  pattern: string
  match_type: WhitelistEntry['match_type']
  tool?: string
  note?: string
}) {
  return api.post<ApiResponse<{ entry: WhitelistEntry }>>(`${BASE}/whitelist`, entry)
}

/** 删除白名单条目 */
export function removeWhitelistEntry(id: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/whitelist/${id}`)
}

/** 待审批列表 */
export function getPendingApprovals() {
  return api.get<ApiResponse<{ requests: ApprovalRequest[] }>>(
    `${BASE}/approvals/pending`
  )
}

/** 审批详情 */
export function getApprovalDetail(requestId: string) {
  return api.get<ApiResponse<{ request: ApprovalRequest }>>(
    `${BASE}/approvals/${requestId}`
  )
}

/** 审批记忆档位（补课 3.2；后端 Literal["exact","similar"]） */
export type ApprovalRemember = 'exact' | 'similar'

/** 批准并重放执行（remember: 缺省仅本次 / exact 记住精确命令 / similar 记住同类） */
export function approveRequest(requestId: string, note = '', remember?: ApprovalRemember) {
  return api.post<ApiResponse<ApproveResult>>(
    `${BASE}/approvals/${requestId}/approve`,
    { note, approved_by: 'user', ...(remember ? { remember } : {}) }
  )
}

/** 拒绝审批 */
export function rejectRequest(requestId: string, note = '') {
  return api.post<ApiResponse<{ approved: boolean }>>(
    `${BASE}/approvals/${requestId}/reject`,
    { note, approved_by: 'user' }
  )
}
