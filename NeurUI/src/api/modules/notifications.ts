import api from '@/api'
import config from '@/config'
import { secureStorage } from '@/utils/security'

const TOKEN_KEY = 'auth_token'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Notification {
  id: string
  /** info/warning/error/success + 业务类型（kb_review/kb_review_result/skill_review/skill_review_result/market_update） */
  type: string
  title: string
  message: string
  read: boolean
  source?: string
  agent_id?: string
  metadata?: Record<string, unknown>
  /** 业务负载数据（后端 data 字段直传） */
  data?: Record<string, unknown>
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

// ---------------------------------------------------------------------------
// SSE 订阅（补课 2.2：替代 60s 轮询）
// ---------------------------------------------------------------------------

/** 铃铛未读数流回调类型 */
export type UnreadStreamCallback = (count: number) => void

/**
 * 订阅未读数 SSE 流（fetch+ReadableStream——EventSource 无法带 Bearer 头）。
 *
 * 返回关闭函数；断流后由调用方决定降级（MainLayout 会回退 60s 轮询）。
 */
export function subscribeUnreadStream(onUnread: UnreadStreamCallback): () => void {
  const controller = new AbortController()
  const token = secureStorage.get(TOKEN_KEY)
  const base = config.apiBaseUrl
  const url = `${base}/notifications/stream?interval=10`

  ;(async () => {
    try {
      const resp = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: controller.signal,
      })
      if (!resp.ok || !resp.body) return
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          try {
            const payload = JSON.parse(line.slice(5).trim()) as { type?: string; count?: number }
            if (payload.type === 'unread' && typeof payload.count === 'number') {
              onUnread(payload.count)
            }
          } catch {
            // 非 JSON 行（keep-alive 注释等）忽略
          }
        }
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        // 断流静默——调用方降级轮询
      }
    }
  })()

  return () => controller.abort()
}
