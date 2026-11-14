import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Agent 行（消费方按各自字段读取；主键以 agent_id ?? id 归一）。 */
export interface AgentRow {
  agent_id?: string
  id?: string
  name?: string
  [key: string]: unknown
}

// ---------------------------------------------------------------------------
// API（P2-21：自 SettingPage 裸写 URL 收编；路径/参数逐字对齐原调用）
// ---------------------------------------------------------------------------

/** List agents（裸数组或 {items}/{agents} 信封，消费方自行归一）。 */
export function listAgents() {
  return api.get<ApiResponse<AgentRow[]>>('/agents')
}
