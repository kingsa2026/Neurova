import api from '@/api'

// ---------------------------------------------------------------------------
// 会话同步（跨渠道）REST 客户端。
//
// 端点契约见 neurova/api/endpoints/session_sync.py（P1-8/P1-9 审计 2026-11-14
// 逐条核对）：会话 CRUD + 历史 + 消息（REST 降级）+ 统计/连接读数。
// 页面（SessionSyncPage）的 4 个调用全部收口在本模块，不再裸写 URL。
// ---------------------------------------------------------------------------

/** 会话行——与后端 SessionResponse / UnifiedSession.to_dict() 同字段。 */
export interface SyncSession {
  session_id: string
  user_id: string
  agent_id: string
  conversation_id: string
  created_at: string
  last_activity: string
  status: string
  active_channels: string[]
  history_size: number
}

/** GET /sync/sessions 响应信封。 */
export interface SyncSessionListResponse {
  total: number
  sessions: SyncSession[]
}

/** POST /sync/sessions 请求体（后端 CreateSessionRequest）。
 * 归属以 token 主体为准；user_id 仅作无身份兜底，前端不自报身份（S-03）。 */
export interface CreateSyncSessionPayload {
  user_id?: string
  agent_id?: string
  external_id?: string | null
  metadata?: Record<string, unknown>
}

/** POST /sync/sessions/{id}/messages 请求体（后端 SendMessageRequest）：
 * 消息正文字段名是 content（P1-8：旧页面发 message 字段，后端不认）。 */
export interface SendSyncMessagePayload {
  content: string
  channel_type?: string
  metadata?: Record<string, unknown>
}

/** POST .../messages 响应。 */
export interface SendSyncMessageResult {
  success: boolean
  event_id: string
  sent_to_channels: number
}

/** DELETE /sync/sessions/{id} 响应（终结会话；后端无 /close 端点，P1-9）。 */
export interface EndSyncSessionResult {
  success: boolean
  session_id: string
}

const BASE = '/sync'

/** 列出当前调用者（token 主体）的同步会话。 */
export function listSyncSessions(params?: { agent_id?: string; status?: string }) {
  return api.get<SyncSessionListResponse>(`${BASE}/sessions`, { params })
}

/** 创建同步会话。 */
export function createSyncSession(data: CreateSyncSessionPayload) {
  return api.post<SyncSession>(`${BASE}/sessions`, data)
}

/** 向会话发送消息（REST 降级路径，复数 /messages）。 */
export function sendSyncSessionMessage(sessionId: string, data: SendSyncMessagePayload) {
  return api.post<SendSyncMessageResult>(
    `${BASE}/sessions/${encodeURIComponent(sessionId)}/messages`, data,
  )
}

/** 终结（删除）会话——后端唯一入口是 DELETE /sync/sessions/{id}。 */
export function endSyncSession(sessionId: string) {
  return api.delete<EndSyncSessionResult>(
    `${BASE}/sessions/${encodeURIComponent(sessionId)}`,
  )
}
