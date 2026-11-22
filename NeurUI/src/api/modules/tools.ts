import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// U8 工具 park 查询（长命令迟交结果的 REST 轮询面，后端 tool_park.py）
// ---------------------------------------------------------------------------

/** GET /v1/tools/park/{park_id} 的回包 data 形态（status: running/completed/failed） */
export interface ParkedToolResult {
  park_id: string
  tool_name?: string
  status: 'running' | 'completed' | 'failed' | string
  poll_after?: number
  max_wait_s?: number
  parked_at?: string
  completed_at?: string
  /** completed 时携带 */
  success?: boolean
  result?: unknown
  /** failed 时携带 */
  error?: string
}

export function getParkedToolResult(parkId: string) {
  return api.get<ApiResponse<ParkedToolResult>>(`/tools/park/${encodeURIComponent(parkId)}`)
}
