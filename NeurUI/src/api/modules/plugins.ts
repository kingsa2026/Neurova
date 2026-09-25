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

/** List all plugins (installed). */
export function getPlugins(params?: PageParams & { category?: string; status?: string }) {
  return api.get<ApiResponse<PaginatedData<Plugin>>>(BASE, { params })
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
