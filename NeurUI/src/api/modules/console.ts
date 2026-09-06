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

export interface DebugResult {
  success: boolean
  output: string
  error?: string
  duration_ms: number
  tool_calls?: { name: string; result: string }[]
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

/** Delete a console session. */
export function deleteConsoleSession(sessionId: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/chat/sessions/${sessionId}`)
}

/** 按拖拽顺序持久化会话排序（QwenPaw /chats/groups/order 对齐）。 */
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

/** Run a debug test for an agent. */
export function debugAgent(agentId: string, prompt: string) {
  return api.post<ApiResponse<DebugResult>>(`${BASE}/debug`, { agent_id: agentId, prompt })
}

/** Push a system message to an agent's conversation. */
export function pushSystemMessage(agentId: string, message: string) {
  return api.post<ApiResponse<null>>(`${BASE}/push`, { agent_id: agentId, message })
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
