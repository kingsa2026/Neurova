import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ParamSchema {
  key: string
  default: any
  type: 'float' | 'int' | 'bool'
  min: number | null
  max: number | null
  description: string
  current: any
}

export interface SettingsUpdatePayload {
  settings: Record<string, any>
}

export interface SettingsResetPayload {
  keys?: string[] | null
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/memory-settings'

/** 获取所有参数（当前值 + 默认值） */
export function getSettings() {
  return api.get<Record<string, any>>(`${BASE}/settings`)
}

/** 获取参数 schema（含类型、范围、描述、当前值） */
export function getSchema() {
  return api.get<ParamSchema[]>(`${BASE}/settings/schema`)
}

/** 获取某个分组的参数 */
export function getSection(section: string) {
  return api.get<Record<string, any>>(`${BASE}/settings/${section}`)
}

/** 批量更新参数并持久化 */
export function updateSettings(data: Record<string, any>) {
  return api.put<{ updated: string[] }>(`${BASE}/settings`, { settings: data })
}

/** 重置参数（全部或指定 key） */
export function resetSettings(keys?: string[] | null) {
  return api.put<{ updated: string[] }>(`${BASE}/settings/reset`, { keys: keys ?? null })
}

/** 导出当前配置 */
export function exportSettings() {
  return api.get<Record<string, any>>(`${BASE}/settings/export`)
}

/** 导入配置 */
export function importSettings(settings: Record<string, any>) {
  return api.put<{ imported: string[] }>(`${BASE}/settings/import`, { settings })
}
