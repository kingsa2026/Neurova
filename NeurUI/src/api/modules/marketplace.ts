import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** 市场技能行（管理面 CRUD 的消费方按宽松行读取，字段以后端契约为准）。 */
export type MarketplaceSkillRow = Record<string, unknown>

/** 市场技能列表查询参（服务端分页 limit/offset；with_total 回传总数）。 */
export interface MarketplaceSkillParams {
  limit?: number
  offset?: number
  with_total?: boolean
  search?: string
  source?: string
}

// ---------------------------------------------------------------------------
// API（P2-21：自 MarketplacePage 裸写 URL 收编；路径/参数逐字对齐原调用）
// ---------------------------------------------------------------------------

/** List marketplace skills（catalog / 远端源搜索，服务端分页）。 */
export function listMarketplaceSkills(params?: MarketplaceSkillParams) {
  return api.get<unknown>('/marketplace/skills', { params })
}

/** List skills installed on the current user's agents. */
export function listInstalledMarketplaceSkills(params?: MarketplaceSkillParams) {
  return api.get<unknown>('/marketplace/installed', { params })
}

/** Admin: sync remote marketplace sources（阿里云/讯飞 → catalog）。 */
export function syncMarketplaceSources() {
  return api.post<unknown>('/marketplace/sync')
}

/** Admin: create a marketplace skill listing. */
export function createMarketplaceSkill(data: Record<string, unknown>) {
  return api.post<unknown>('/marketplace/skills', data)
}

/** Admin: update a marketplace skill listing. */
export function updateMarketplaceSkill(skillId: string, data: Record<string, unknown>) {
  return api.put<unknown>(`/marketplace/skills/${skillId}`, data)
}

/** Admin: delete a marketplace skill listing. */
export function deleteMarketplaceSkill(skillId: string) {
  return api.delete<unknown>(`/marketplace/skills/${skillId}`)
}

/** Install a marketplace skill（data 缺省 = 无体安装；{force:true} = 升级重装）。 */
export function installMarketplaceSkill(skillId: string, data?: Record<string, unknown>) {
  return api.post<unknown>(`/marketplace/skills/${skillId}/install`, data)
}

/** Uninstall a marketplace skill. */
export function uninstallMarketplaceSkill(skillId: string) {
  return api.delete<unknown>(`/marketplace/skills/${skillId}/install`)
}
