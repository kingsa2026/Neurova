import api from '@/api'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Plugin {
  id: string
  name: string
  description: string
  version: string
  author?: string
  category?: string
  installed: boolean
  loaded: boolean
  enabled: boolean
  dependencies?: string[]
  config?: Record<string, unknown>
  created_at?: string
  updated_at?: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/plugins'

/** 后端 /plugins 只认 page/size（plugin.py list_plugins(page=1, size=20)，
 * 无 limit/offset）。统一分页词是 limit/offset（P1-13），换算只在这里做一次：
 * offset须为 limit 整数倍（分页器本就按 offset=(page-1)*size 发）。
 */
function toBackendPageQuery({ limit, offset }: PageParams = {}) {
  const size = limit ?? 20
  const page = Math.floor((offset ?? 0) / size) + 1
  return { page, size }
}

/** List all plugins (installed). */
export function getPlugins(params?: PageParams & { category?: string; status?: string }) {
  const { limit, offset, ...filters } = params ?? {}
  return api.get<ApiResponse<PaginatedData<Plugin>>>(BASE, {
    params: { ...toBackendPageQuery({ limit, offset }), ...filters },
  })
}

/** Get a single plugin. */
export function getPlugin(id: string) {
  return api.get<ApiResponse<Plugin>>(`${BASE}/${id}`)
}

/** Install a discovered plugin. */
export function installPlugin(id: string) {
  return api.post<ApiResponse<Plugin>>(`${BASE}/${id}/install`)
}

/** Load a plugin into memory. */
export function loadPlugin(id: string) {
  return api.post<ApiResponse<null>>(`${BASE}/${id}/load`)
}

/** Unload a plugin from memory. */
export function unloadPlugin(id: string) {
  return api.post<ApiResponse<null>>(`${BASE}/${id}/unload`)
}

/** Enable a plugin. */
export function enablePlugin(id: string) {
  return api.post<ApiResponse<null>>(`${BASE}/${id}/enable`)
}

/** Disable a plugin. */
export function disablePlugin(id: string) {
  return api.post<ApiResponse<null>>(`${BASE}/${id}/disable`)
}
