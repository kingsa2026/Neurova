import api from '@/api'
import type { ApiResponse, LimitOffsetParams, PaginatedData, PageParams } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Skill {
  id: string
  name: string
  description: string
  version: string
  author?: string
  category?: string
  tags?: string[]
  installed?: boolean
  enabled?: boolean
  config?: Record<string, unknown>
  created_at?: string
  updated_at?: string
}

export interface SkillCreatePayload {
  name: string
  description: string
  version?: string
  category?: string
  tags?: string[]
  config?: Record<string, unknown>
}

export interface SkillUpdatePayload {
  name?: string
  description?: string
  version?: string
  category?: string
  tags?: string[]
  config?: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/skill-pool'

/** List public skills available in the marketplace.
 *
 * 2026-09-03: 原调 /skill-pool/public(僵尸空 dict, 无人填充)。
 * 与 /marketplace 页同源: catalog/远端源搜索, 登录用户可读。
 */
export function getPublicSkills(
  params?: LimitOffsetParams & { category?: string; search?: string },
) {
  return api.get<ApiResponse<PaginatedData<Skill>>>('/marketplace/skills', {
    params: {
      ...params,
      limit: params?.limit ?? 100,
      offset: params?.offset ?? 0,
      with_total: true,
    },
  })
}

/** List private (installed) skills for an agent. */
export function getPrivateSkills(agentId: string, params?: PageParams) {
  return api.get<ApiResponse<PaginatedData<Skill>>>(`${BASE}/private`, { params: { ...params, agent_id: agentId } })
}

/** Get a single skill by ID. */
export function getSkill(skillId: string) {
  return api.get<ApiResponse<Skill>>(`${BASE}/${skillId}`)
}

/** Create a new custom skill. */
export function createSkill(data: SkillCreatePayload) {
  return api.post<ApiResponse<Skill>>(BASE, data)
}

/** Update an existing skill. */
export function updateSkill(skillId: string, data: SkillUpdatePayload) {
  return api.put<ApiResponse<Skill>>(`${BASE}/${skillId}`, data)
}

/** Delete a skill. */
export function deleteSkill(skillId: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/${skillId}`)
}

/** Install a marketplace skill (canonical /marketplace/skills/{id}/install；
 *  原 /skill-pool/{id}/install 路由不存在恒 404，ADR 0013 写侧迁移漏项）。 */
export function installSkill(skillId: string, agentId: string) {
  return api.post<ApiResponse<Skill>>(`/marketplace/skills/${skillId}/install`, { agent_id: agentId })
}

/** Share a private skill to the public pool. */
export function shareSkill(skillId: string) {
  return api.post<ApiResponse<null>>(`${BASE}/${skillId}/share`)
}

/** Push a skill update to the public pool. */
export function pushSkill(skillId: string) {
  return api.post<ApiResponse<null>>(`${BASE}/${skillId}/push`)
}

// ---------------------------------------------------------------------------
// Marketplace skill submission & admin review (2026-09-01)
// ---------------------------------------------------------------------------

export interface SkillSubmission {
  id: string
  skill_id: string
  name: string
  description?: string
  version?: string
  category?: string
  tags?: string[]
  download_url?: string
  author?: string
  submitted_by?: string
  submitted_by_name?: string
  status: 'pending' | 'approved' | 'rejected'
  review_note?: string | null
  created_at?: number
  decided_at?: number | null
}

export interface SkillSubmitPayload {
  skill_id: string
  name: string
  description?: string
  version?: string
  category?: string
  tags?: string[]
  download_url?: string
  author?: string
}

/** Submit a skill for marketplace review (pending until admin approves). */
export function submitSkillForReview(data: SkillSubmitPayload) {
  return api.post<ApiResponse<SkillSubmission>>(`${BASE}/skills/submit`, data)
}

/** Admin: list marketplace skill submissions (default: pending). */
export function listSkillSubmissions(reviewStatus: string = 'pending') {
  return api.get<ApiResponse<{ items: SkillSubmission[]; total: number }>>(
    `${BASE}/skill-submissions`,
    { params: { review_status: reviewStatus } },
  )
}

/** Admin: approve or reject a skill submission. */
export function reviewSkillSubmission(id: string, approve: boolean, note = '') {
  return api.post<ApiResponse<SkillSubmission>>(`${BASE}/skill-submissions/${id}/review`, {
    approve,
    note,
  })
}

// ---------------------------------------------------------------------------
// Skill Market (ZIP / Remote Install)
// ---------------------------------------------------------------------------

/** Install a skill from a remote URL. */
export function installSkillFromUrl(url: string, version?: string) {
  return api.post<ApiResponse<{ url: string }>>(`${BASE}/install-from-url`, { url, version })
}

/** Install a skill from a ZIP file upload. */
export function installSkillFromZip(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return api.post<ApiResponse<{ message: string }>>(`${BASE}/install-from-zip`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

// ---------------------------------------------------------------------------
// Agent Skill Management (uninstall / list / toggle / execute)
// ---------------------------------------------------------------------------

/** Uninstall a marketplace skill (canonical DELETE /marketplace/skills/{id}/install；
 *  原走 /skill-pool/private/{id}/push 是"取消推送"语义——对市场技能假成功不落盘，
 *  刷新后 installed 又回 true。ADR 0013 写侧迁移漏项之二。） */
export function uninstallSkill(skillId: string, agentId: string) {
  return api.delete<ApiResponse<null>>(`/marketplace/skills/${skillId}/install`, {
    params: { agent_id: agentId },
  })
}

/** List all skills installed on an agent. */
export function getAgentSkills(agentId: string) {
  return api.get<ApiResponse<Skill[]>>(`${BASE}/agent/${agentId}/skills`)
}

/** Enable or disable a private skill. */
export function enableSkill(skillId: string, enabled: boolean) {
  return api.put<ApiResponse<Skill>>(`${BASE}/private/${skillId}`, {
    config: { enabled },
  })
}

/** Execute a private skill with arguments on behalf of an agent. */
export function executeSkill(skillId: string, agentId: string, args: Record<string, unknown>) {
  return api.post<ApiResponse<unknown>>(`${BASE}/private/${skillId}/execute`, {
    agent_id: agentId,
    arguments: args,
  })
}
