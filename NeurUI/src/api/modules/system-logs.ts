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
  // 后端契约是 `DELETE /api/v1/logs`（`endpoints/logs.py` 的 `@router.delete("")`）；
  // 原写 `POST /logs/clear` 从未注册过路由，LogPage 的「清空日志」实测恒 404。
  return api.delete<ApiResponse<null>>(BASE)
}
