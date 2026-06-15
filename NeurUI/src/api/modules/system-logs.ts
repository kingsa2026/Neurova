import api from '@/api'
import type { ApiResponse, PaginatedData } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LogEntry {
  id: string
  timestamp: string
  level: string
  message: string
  source: string
}

export interface LogListParams {
  page?: number
  page_size?: number
  level?: string
  keyword?: string
  start?: string
  end?: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/logs'

/** List system logs with optional filters. */
export function listLogs(params?: LogListParams) {
  return api.get<ApiResponse<PaginatedData<LogEntry>>>(BASE, { params })
}

/** Clear all logs. */
export function clearLogs() {
  return api.post<ApiResponse<null>>(`${BASE}/clear`)
}
