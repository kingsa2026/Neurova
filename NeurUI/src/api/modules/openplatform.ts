import api from '@/api'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface APIKey {
  id: string
  name: string
  key_prefix: string
  scopes: string[]
  enabled: boolean
  last_used?: string
  expires_at?: string
  created_at: string
}

export interface APIKeyCreatePayload {
  name: string
  scopes: string[]
  expires_at?: string
}

export interface APIKeyCreateResult {
  id: string
  name: string
  key: string // Full key only returned on creation
  scopes: string[]
  expires_at?: string
}

export interface APIKeyUsage {
  key_id: string
  period: string
  total_requests: number
  by_endpoint: { endpoint: string; count: number }[]
  daily_trend: { date: string; count: number }[]
}

export interface ScopeInfo {
  name: string
  description: string
  category: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/openplatform'

/** List all API keys. */
export function getAPIKeys(params?: PageParams) {
  return api.get<ApiResponse<PaginatedData<APIKey>>>(`${BASE}/keys`, { params })
}

/** Create a new API key. */
export function createAPIKey(data: APIKeyCreatePayload) {
  return api.post<ApiResponse<APIKeyCreateResult>>(`${BASE}/keys`, data)
}

/** Update an API key (rename, change scopes). */
export function updateAPIKey(id: string, data: Partial<APIKeyCreatePayload & { enabled: boolean }>) {
  return api.put<ApiResponse<APIKey>>(`${BASE}/keys/${id}`, data)
}

/** Delete/revoke an API key. */
export function deleteAPIKey(id: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/keys/${id}`)
}

/** Get available scopes. */
export function getScopes() {
  return api.get<ApiResponse<ScopeInfo[]>>(`${BASE}/scopes`)
}

/** Get usage statistics for an API key. */
export function getAPIKeyUsage(keyId: string, params?: { period?: string }) {
  return api.get<ApiResponse<APIKeyUsage>>(`${BASE}/keys/${keyId}/usage`, { params })
}

/** Rotate an API key (generate new key, revoke old). */
export function rotateAPIKey(id: string) {
  return api.post<ApiResponse<APIKeyCreateResult>>(`${BASE}/keys/${id}/rotate`)
}

/** Get open platform overview stats. */
export function getPlatformStats() {
  return api.get<ApiResponse<{ total_keys: number; active_keys: number; total_requests_24h: number }>>(`${BASE}/stats`)
}
