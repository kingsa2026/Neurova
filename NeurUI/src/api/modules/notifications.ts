import api from '@/api'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Notification {
  id: string
  type: 'info' | 'warning' | 'error' | 'success'
  title: string
  message: string
  read: boolean
  source?: string
  agent_id?: string
  metadata?: Record<string, unknown>
  created_at: string
}

export interface UnreadCount {
  total: number
  info: number
  warning: number
  error: number
  success: number
}

export interface PushStats {
  total_sent: number
  total_delivered: number
  total_failed: number
  channels: { name: string; count: number }[]
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/notifications'

/** List notifications. */
export function getNotifications(params?: PageParams & { type?: string; read?: boolean; agent_id?: string }) {
  return api.get<ApiResponse<PaginatedData<Notification>>>(BASE, { params })
}

/** Get unread notification counts. */
export function getUnreadCount() {
  return api.get<ApiResponse<UnreadCount>>(`${BASE}/unread-count`)
}

/** Mark a notification as read. */
export function markRead(id: string) {
  return api.post<ApiResponse<null>>(`${BASE}/${id}/read`)
}

/** Mark all notifications as read. */
export function markAllRead() {
  return api.post<ApiResponse<null>>(`${BASE}/mark-all-read`)
}

/** Delete a notification. */
export function deleteNotification(id: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/${id}`)
}

/** Get push statistics. */
export function getPushStats() {
  return api.get<ApiResponse<PushStats>>(`${BASE}/push-statistics`)
}
