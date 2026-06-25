import api from '@/api'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/response'

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

/** List public skills available in the marketplace. */
export function getPublicSkills(params?: PageParams & { category?: string; search?: string }) {
  return api.get<ApiResponse<PaginatedData<Skill>>>(`${BASE}/public`, { params })
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

/** Install a public skill into an agent's private pool. */
export function installSkill(skillId: string, agentId: string) {
  return api.post<ApiResponse<Skill>>(`${BASE}/${skillId}/install`, { agent_id: agentId })
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
// Skill Market (ZIP / Remote Install)
// ---------------------------------------------------------------------------

/** Install a skill from a remote URL. */
export function installSkillFromUrl(url: string, version?: string) {
  return api.post<ApiResponse<{ url: string }>>('/skill-market/install', { url, version })
}

/** Install a skill from a ZIP file upload. */
export function installSkillFromZip(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return api.post<ApiResponse<{ message: string }>>('/skill-market/install/zip', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
