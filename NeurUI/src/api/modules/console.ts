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

/**
 * Stream a chat response via SSE.
 * Returns the EventSource URL and headers for the caller to manage.
 */
export function getConsoleChatSSEUrl(agentId: string, message: string, sessionId?: string) {
  const base = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const params = new URLSearchParams({ agent_id: agentId, message })
  if (sessionId) params.set('session_id', sessionId)
  return `${base}${BASE}/chat/stream?${params.toString()}`
}

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
