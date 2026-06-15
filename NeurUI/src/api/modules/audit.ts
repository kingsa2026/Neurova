import api from '@/api'
import { request } from '@/api'
import type { ApiResponse, PaginatedData } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AuditRecord {
  id: string
  timestamp: string
  user: string
  action: string
  resource: string
  details?: Record<string, unknown>
}

export interface AuditStats {
  total: number
  today: number
  warnings: number
}

export interface AuditListParams {
  page?: number
  page_size?: number
  user?: string
  action?: string
  start?: string
  end?: string
}

export interface AuditListResult {
  items: AuditRecord[]
  total: number
  stats: AuditStats
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/audit'

/** List audit records with optional filters. */
export function listAuditRecords(params?: AuditListParams) {
  return api.get<ApiResponse<AuditListResult>>(BASE, { params })
}

/** Export audit records as JSON blob. */
export function exportAudit(params?: AuditListParams) {
  return request.get(`${BASE}/export`, { params, responseType: 'blob' }) as unknown as Promise<Blob>
}
