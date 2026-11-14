import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ConsoleSession {
  id: string
  agent_id?: string
  status: 'active' | 'idle' | 'error'
  messages_count: number
  created_at: string
  updated_at?: string
}

/** 会话时间线事件（后端 append-only JSONL 的原样形态，字段按事件类型变化）。 */
export type ConsoleTimelineEvent = Record<string, unknown>

export interface ConsoleTimelineResult {
  sessionId: string
  events: ConsoleTimelineEvent[]
  total: number
}

export interface UploadResult {
  filename: string
  path: string
  size: number
  mime_type: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/console'

/** Get console session list. */
export function getConsoleSessions(params?: { agent_id?: string; limit?: number }) {
  return api.get<ApiResponse<ConsoleSession[]>>(`${BASE}/chat/sessions`, { params })
}

/** Get the file-message history of a console session. */
export function getConsoleChatHistory(sessionId: string) {
  return api.get<ApiResponse<{ messages: unknown[]; session_id: string }>>(
    `${BASE}/chat/history?session_id=${encodeURIComponent(sessionId)}`,
  )
}

/**
 * 取会话时间线（SSE 事件的 append-only 重放面）。
 *
 * limit<=0 表示「全量」——后端把 0 当作无上限，故不把 0 发上线。
 * 服务端语义为「取最近 N 条」，调用方无须关心截断方向。
 */
export function getConsoleSessionTimeline(sessionId: string, limit = 0) {
  const path = `${BASE}/chat/sessions/${encodeURIComponent(sessionId)}/timeline`
  const query = limit > 0 ? `?limit=${Math.trunc(limit)}` : ''
  return api.get<ApiResponse<{ session_id: string; events: ConsoleTimelineEvent[]; total: number }>>(path + query)
}

/** Delete a console session. */
export function deleteConsoleSession(sessionId: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/chat/sessions/${sessionId}`)
}

/** 按拖拽顺序持久化会话排序。 */
export function reorderConsoleSessions(agentId: string, orderedIds: string[]) {
  return api.post<ApiResponse<{ agent_id: string; ordered_ids: string[] }>>(
    `${BASE}/chat/sessions/reorder`,
    { agent_id: agentId, ordered_ids: orderedIds },
  )
}

/** Archive a console session (hidden from history list, restorable). */
export function archiveConsoleSession(sessionId: string) {
  return api.post<ApiResponse<null>>(`${BASE}/chat/sessions/${sessionId}/archive`)
}

/** Restore an archived console session back to the normal list. */
export function unarchiveConsoleSession(sessionId: string) {
  return api.post<ApiResponse<null>>(`${BASE}/chat/sessions/${sessionId}/unarchive`)
}

/** Send a chat message via REST (non-streaming). Returns the assistant response. */
export function sendConsoleMessage(agentId: string, message: string, sessionId?: string) {
  return api.post<ApiResponse<{ response: string; session_id: string; tool_calls?: any[] }>>(`${BASE}/chat`, {
    agent_id: agentId,
    message,
    session_id: sessionId,
  })
}

// 流式入口不在 console 域：真实 SSE 端点在 chat 域
//（`neurova/api/endpoints/chat.py` 的流式对话路由）。此前的
// getConsoleChatSSEUrl 拼的是本域不存在的流式路径，自身也零调用
//（审计 2026-11-04 P1-8），已退役。

/** Upload a file to the console context. */
export function uploadConsoleFile(file: File, agentId?: string) {
  const formData = new FormData()
  formData.append('file', file)
  if (agentId) formData.append('agent_id', agentId)
  return api.upload<ApiResponse<UploadResult>>(`${BASE}/upload`, file, 'file', agentId ? { agent_id: agentId } : undefined)
}

/**
 * Get WebSocket URL for real-time console.
 */
export function getConsoleWSUrl(agentId: string) {
  const base = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const wsBase = base.replace(/^http/, 'ws')
  return `${wsBase}${BASE}/ws?agent_id=${agentId}`
}

// ---------------------------------------------------------------------------
// 反馈质量闭环：点赞/点踩统计（迭代② stats 端点）
// ---------------------------------------------------------------------------

export interface FeedbackRecentItem {
  session_id: string
  timestamp: string
  content: string
  feedback: 'like' | 'dislike'
}

export interface FeedbackStats {
  agent_id: string
  sessions_scanned: number
  total_feedback: number
  like: number
  dislike: number
  recent: FeedbackRecentItem[]
}

/** Get like/dislike feedback stats aggregated per agent (reply quality). */
export function getFeedbackStats(params?: { agent_id?: string; limit?: number }) {
  return api.get<ApiResponse<FeedbackStats>>(`${BASE}/chat/feedback/stats`, { params })
}

// ---------------------------------------------------------------------------
// 运维/转向/音频面（P2-33：自 ChatPage 裸写 URL 收编进 api modules）
// ---------------------------------------------------------------------------

/** 音频合成流式端点路径（页面以 fetch 流式消费，路径单源在此）。 */
export const AUDIO_SYNTHESIZE_STREAM_PATH = '/audio/synthesize-stream'

/** 向正在运行的会话轮发送转向指令（steer）。 */
export function steerConsoleChat(sessionId: string, message: string) {
  return api.post<ApiResponse<null>>(`${BASE}/chat/steer`, { session_id: sessionId, message })
}

/** 取运行中任务列表（生成状态提示的数据源）。 */
export function getConsoleTasks() {
  return api.get<ApiResponse<{ tasks: unknown[] }>>(`${BASE}/tasks`)
}

/** 取某会话的停靠运行（parked runs）；scope='subagents' 读子任务台账。 */
export function getConsoleChatRuns(sessionId: string, scope?: string) {
  return api.get<ApiResponse<{ runs: unknown[] }>>(`${BASE}/chat/runs`, {
    params: { session_id: sessionId, ...(scope ? { scope } : {}) },
  })
}

/** 音频（TTS/ASR）能力状态。 */
export function getAudioStatus() {
  return api.get<ApiResponse<Record<string, unknown>>>('/audio/status')
}

// ---------------------------------------------------------------------------
// 会话生命周期/轮次操作（P2-21：自 ChatPage / useChat / useSubAgentWindows /
// CrossSessionSearch 裸写 URL 收编；路径/参数逐字对齐原调用）
// ---------------------------------------------------------------------------

/** 取消某会话运行中的任务（真停止，不只是断流）。 */
export function stopConsoleChat(sessionId: string) {
  return api.post<ApiResponse<null>>(`${BASE}/chat/stop?session_id=${encodeURIComponent(sessionId)}`)
}

/** 会话默认标题 → 会话语义概括自动填充（增强，失败静默由调用方兜底）。 */
export function autoTitleConsoleSession(sessionId: string) {
  return api.post<ApiResponse<{ title?: string }>>(`${BASE}/chat/sessions/${sessionId}/auto-title`)
}

/** Create a new chat session（后端回传 session_id 防前后端 id 漂移）。 */
export function createConsoleSession(agentId: string, title: string) {
  return api.post<ApiResponse<{ session_id?: string; id?: string }>>(`${BASE}/chat/new`, {
    agent_id: agentId,
    title,
  })
}

/** List archived sessions of an agent（存档卡片页数据源）。 */
export function getArchivedConsoleSessions(params?: { agent_id?: string }) {
  return api.get<ApiResponse<ConsoleSession[]>>(`${BASE}/chat/sessions/archived`, { params })
}

/** Rename a session（PUT 新标题）。 */
export function renameConsoleSession(sessionId: string, title: string) {
  return api.put<ApiResponse<null>>(`${BASE}/chat/sessions/${sessionId}`, { title })
}

/** Pin/unpin a session. */
export function pinConsoleSession(sessionId: string, pinned: boolean) {
  return api.post<ApiResponse<null>>(`${BASE}/chat/sessions/${sessionId}/pin`, { pinned })
}

/** Delete one round（user 消息 + 相邻 assistant 回复）。 */
export function deleteConsoleRound(sessionId: string, timestamp: string) {
  return api.delete<ApiResponse<null>>(
    `${BASE}/chat/rounds?session_id=${encodeURIComponent(sessionId)}&timestamp=${encodeURIComponent(timestamp)}`,
  )
}

/** Like/dislike an assistant reply（feedback=null 取消已有反馈）。 */
export function sendConsoleFeedback(
  sessionId: string,
  timestamp: string,
  feedback: 'like' | 'dislike' | null,
) {
  return api.post<ApiResponse<null>>(`${BASE}/chat/feedback`, {
    session_id: sessionId,
    timestamp,
    feedback,
  })
}

/** Fork a session，复制 untilTimestamp 之前的历史（缺省 = 整个会话）。 */
export function forkConsoleSession(sessionId: string, untilTimestamp?: string) {
  return api.post<ApiResponse<{ new_session_id?: string }>>(
    `${BASE}/chat/sessions/${sessionId}/fork`,
    { until_timestamp: untilTimestamp || null },
  )
}

/** Set/clear a message checkpoint（持久化到消息 metadata）。 */
export function setConsoleCheckpoint(sessionId: string, timestamp: string, active: boolean) {
  return api.post<ApiResponse<null>>(`${BASE}/chat/checkpoint`, {
    session_id: sessionId,
    timestamp,
    active,
  })
}
