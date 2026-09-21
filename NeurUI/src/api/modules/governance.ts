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

// ---------------------------------------------------------------------------
// 技能归档 / 回滚（工单 011）
//
// 后端 `get_archives` / `rollback_skill` 此前在顶层零生产调用方 —— 归档只写不读。
// 归档列表是"能退回哪一版"的唯一读面；回滚是最大破坏动作，必须带操作者留痕。
// ---------------------------------------------------------------------------

/** 一份归档快照（后端 `SkillExperienceStore._archives` 的条目形状） */
export interface SkillArchiveEntry {
  version: string
  description: string
  archived_at?: number
  reason?: string
}

export interface SkillArchives {
  skill_id: string
  archives: SkillArchiveEntry[]
}

export interface SkillRollbackResult {
  rolled_back: boolean
  skill_id: string
  operator: string
  /** 回滚后剩余归档数（0 = 窗口已用尽，再点会被后端 409 拒绝） */
  archives_left: number
}

/** 归档读面：该技能保留的可回滚快照（未装配返 503，不是空列表） */
export function getSkillArchives(skillId: string, agentId?: string) {
  return api.get<ApiResponse<SkillArchives>>(
    `${BASE}/skills/${skillId}/archives`,
    { params: agentId ? { agent_id: agentId } : {} }
  )
}

/** 回滚写面：退回最近一次归档；归档为空时后端返 409 */
export function rollbackSkill(skillId: string, operator: string, agentId?: string) {
  return api.post<ApiResponse<SkillRollbackResult>>(
    `${BASE}/skills/${skillId}/rollback`,
    { operator, ...(agentId ? { agent_id: agentId } : {}) }
  )
}
