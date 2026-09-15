import api from '@/api'
import type { ApiResponse, LimitOffsetParams, PaginatedData } from '@/types/response'

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

// ---------------------------------------------------------------------------
// 三层技能库（闭环核验轮 V）：公共库真源 + 用户私库 CRUD
// 旧 getPrivateSkills/getSkill/createSkill/updateSkill/deleteSkill/shareSkill/
// pushSkill 与后端 /private 系路由断裂（404/落幽灵 _all 桶），消费者仅
// SkillPoolPage，已整体迁移至下列 me/public 库函数，旧函数删除。
// ---------------------------------------------------------------------------

/** 库条目（后端 SkillInfo 契约：主键字段是 skill_id，非 id）。 */
export interface LibrarySkill {
  skill_id: string
  name: string
  description?: string
  category?: string
  version?: string
  scope?: string
  owner_id?: string
  enabled?: boolean
  shared?: boolean
  usage?: Record<string, unknown>
}

/** 公共技能库（pool=public，审批物化/管理员登记的条目，所有用户可见可读）。 */
export function listPublicLibrarySkills() {
  return api.get<ApiResponse<LibrarySkill[]>>(`${BASE}/public`)
}

/** 我的用户私库（pool=user，ukey=u:{user_id}；接收 agent 推送与公共升级）。 */
export function listMySkills() {
  return api.get<ApiResponse<LibrarySkill[]>>(`${BASE}/me/skills`)
}

/** 用户私库创建技能。 */
export function createMySkill(data: SkillCreatePayload) {
  return api.post<ApiResponse<LibrarySkill>>(`${BASE}/me/skills`, data)
}

/** 用户私库更新（enabled 走行级真通道，V5）。 */
export function updateMySkill(skillId: string, data: SkillUpdatePayload & { enabled?: boolean }) {
  return api.put<ApiResponse<LibrarySkill>>(`${BASE}/me/skills/${skillId}`, data)
}

/** 用户私库删除（属主自决，无确认队列；跨库才走 transfers）。 */
export function deleteMySkill(skillId: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/me/skills/${skillId}`)
}

/** 公共库→我的私库自助安装：副本+血缘（公共升级广播据此可达）。 */
export function installPublicToMine(skillId: string) {
  return api.post<ApiResponse<{ applied: string }>>(`${BASE}/me/skills/${skillId}/from-public`)
}

/** Install a marketplace skill (canonical /marketplace/skills/{id}/install；
 *  原 /skill-pool/{id}/install 路由不存在恒 404，ADR 0013 写侧迁移漏项）。 */
export function installSkill(skillId: string, agentId: string) {
  return api.post<ApiResponse<Skill>>(`/marketplace/skills/${skillId}/install`, { agent_id: agentId })
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
  /** 发布来源=本人用户私库条目（服务端快照 tool_sequence 载荷，V 轮） */
  pool_skill_id?: string
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

/** Install a skill from a remote URL. target=''(默认)=agent 技能池（现状语义）；
 *  target='me'=落当前账号用户私库（V 轮，技能库页导入语义）。 */
export function installSkillFromUrl(url: string, version?: string, target?: string) {
  return api.post<ApiResponse<{ url: string }>>(`${BASE}/install-from-url`, { url, version, target })
}

/** Install a skill from a ZIP file upload. target 语义同上。 */
export function installSkillFromZip(file: File, target?: string) {
  const formData = new FormData()
  formData.append('file', file)
  if (target) formData.append('target', target)
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

/** Enable or disable a private skill（V5：agent 定库 + enabled 行级真通道。
 *  旧实现 config.enabled 从不触发行级 enabled 且缺 agent_id 落 default 库）。 */
export function enableSkill(skillId: string, enabled: boolean, agentId = 'default') {
  return api.put<ApiResponse<Skill>>(`${BASE}/private/${skillId}`, { enabled }, {
    params: { agent_id: agentId },
  })
}

/** Execute a private skill with arguments on behalf of an agent. */
export function executeSkill(skillId: string, agentId: string, args: Record<string, unknown>) {
  return api.post<ApiResponse<unknown>>(`${BASE}/private/${skillId}/execute`, {
    agent_id: agentId,
    arguments: args,
  })
}


// ---------------------------------------------------------------------------
// C10 治理收紧（2026-09-12）：待审产物审批面（技能 + 经验）
// ---------------------------------------------------------------------------

export interface PendingExperience {
  record_id: string
  skill_id: string
  source: string
  content: string
  context?: string
  created_at?: number
}

export interface PendingSkillItem {
  template_id?: string
  skill_id?: string
  name?: string
  description?: string
  [key: string]: unknown
}

/** C10 审批面：列出待审自动技能（评审闸默认开）。 */
export function listPendingSkills(agentId: string = '_all') {
  return api.get<ApiResponse<PendingSkillItem[]>>(`${BASE}/agent/${agentId}/pending-skills`)
}

/** C10 审批面：批准待审技能。 */
export function approvePendingSkill(agentId: string, templateId: string) {
  return api.post(`${BASE}/agent/${agentId}/pending-skills/${templateId}/approve`)
}

/** C10 审批面：拒绝待审技能。 */
export function rejectPendingSkill(agentId: string, templateId: string) {
  return api.post(`${BASE}/agent/${agentId}/pending-skills/${templateId}/reject`)
}

/** C10 审批面：列出待审的自动化 applied 经验记录。 */
export function listPendingExperiences(agentId: string = '_all') {
  return api.get<ApiResponse<PendingExperience[]>>(`${BASE}/agent/${agentId}/pending-experiences`)
}

/** C10 审批面：批准待审经验（注入技能描述并计入重建阈值）。 */
export function approvePendingExperience(agentId: string, recordId: string) {
  return api.post(`${BASE}/agent/${agentId}/pending-experiences/${recordId}/approve`)
}

/** C10 审批面：拒绝待审经验。 */
export function rejectPendingExperience(agentId: string, recordId: string) {
  return api.post(`${BASE}/agent/${agentId}/pending-experiences/${recordId}/reject`)
}

// ---------------------------------------------------------------------------
// Wave H-W4 三层技能库流转（agent→user 推送 / 公共库升级，均需确认）
// ---------------------------------------------------------------------------

export interface SkillTransfer {
  transfer_id: string
  transfer_type: string
  skill_id: string
  src_pool: string
  src_owner: string
  dst_pool: string
  dst_owner: string
  confirm_owner?: string
  kind: string
  version: string
  name: string
  status: string
  note?: string
  created_at?: number
}

/** 发起流转提案（当前仅 agent_to_user；进确认队列）。 */
export function createSkillTransfer(body: {
  transfer_type: string
  skill_id: string
  src_pool: string
  src_owner: string
  note?: string
}) {
  return api.post<ApiResponse<SkillTransfer>>(`${BASE}/transfers`, body)
}

/** 我的待确认流转队列。 */
export function listSkillTransfers(status = 'pending') {
  return api.get<ApiResponse<{ items: SkillTransfer[]; total: number }>>(`${BASE}/transfers`, {
    params: { status },
  })
}

/** 确认流转：落副本/原地升级（账本保留）。 */
export function acceptSkillTransfer(transferId: string, note = '') {
  return api.post(`${BASE}/transfers/${transferId}/accept`, { note })
}

/** 拒绝流转：仅记账不动库。 */
export function rejectSkillTransfer(transferId: string, note = '') {
  return api.post(`${BASE}/transfers/${transferId}/reject`, { note })
}
