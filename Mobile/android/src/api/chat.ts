/**
 * 对话 API：SSE 流式（主通道，POST /chat/stream）+ 会话/历史（REST）。
 * 事件契约对齐 neurova/api/endpoints/chat.py：start/message/reasoning/retry/parked/error/done，
 * 心跳为 SSE 注释行 ": ping"（解析时忽略）。
 */
import { useServersStore } from '@/stores/servers'
import { storageGet } from '@/utils/session'
import type { ChatSessionItem } from '@/types'

/** 带认证的 fetch：401 时单飞刷新 token 并重试一次（对齐 axios 拦截器语义） */
export async function authedFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const { STORAGE_KEYS, storageGet } = await import('@/utils/session')
  const { refreshAccessToken } = await import('@/utils/http')
  const token = (await storageGet(STORAGE_KEYS.accessToken)) ?? ''
  const first = await fetch(url, {
    ...options,
    headers: { ...(options.headers ?? {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  })
  if (first.status !== 401) return first
  try {
    const refreshToken = (await storageGet(STORAGE_KEYS.refreshToken)) ?? ''
    if (!refreshToken) return first
    await refreshAccessToken()
    const newToken = (await storageGet(STORAGE_KEYS.accessToken)) ?? ''
    return fetch(url, {
      ...options,
      headers: { ...(options.headers ?? {}), ...(newToken ? { Authorization: `Bearer ${newToken}` } : {}) },
    })
  } catch {
    return first
  }
}


export interface ChatStreamHandlers {
  onStart?: (info: { request_id: string; session_id: string }) => void
  onMessage: (chunk: string) => void
  onReasoning?: (chunk: string) => void
  onStatus?: (info: { kind: 'retry' | 'parked' | 'upstream_status'; payload: Record<string, unknown> }) => void
  onError?: (message: string) => void
  onDone?: (info: { request_id?: string; session_id?: string }) => void
}

export interface ChatStreamOptions {
  message: string
  agentId?: string
  sessionId?: string
  signal?: AbortSignal
}

/** 解析 SSE 文本帧流（按空行分帧，event:/data: 成对） */
function consumeSseBuffer(buffer: string, onFrame: (event: string, data: string) => void): string {
  const frames = buffer.split(/\r?\n\r?\n/)
  const rest = frames.pop() ?? ''
  for (const frame of frames) {
    let event = 'message'
    const dataLines: string[] = []
    for (const line of frame.split(/\r?\n/)) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
      // ": ping" 心跳注释行直接忽略
    }
    if (dataLines.length) onFrame(event, dataLines.join('\n'))
  }
  return rest
}

export async function streamChat(opts: ChatStreamOptions, h: ChatStreamHandlers): Promise<void> {
  const servers = useServersStore()
  const token = (await storageGet('neurova.auth.access_token')) ?? ''
  const r = await authedFetch(`${servers.apiBase}/chat/stream`, {
    method: 'POST',
    signal: opts.signal,
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      Authorization: `Bearer ${token}`,
      'X-Request-ID': crypto.randomUUID(),
    },
    body: JSON.stringify({
      message: opts.message,
      agent_id: opts.agentId || 'default',
      ...(opts.sessionId ? { session_id: opts.sessionId } : {}),
    }),
  })
  if (!r.ok || !r.body) {
    let detail = `HTTP ${r.status}`
    try {
      const j = await r.json()
      detail = j?.detail || j?.message || detail
    } catch { /* 保留状态码文案 */ }
    h.onError?.(detail)
    return
  }
  const reader = r.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let done = false
  while (!done) {
    const { value, done: eof } = await reader.read()
    if (eof) break
    buffer += decoder.decode(value, { stream: true })
    buffer = consumeSseBuffer(buffer, (event, data) => {
      let payload: Record<string, unknown> = {}
      try { payload = data ? JSON.parse(data) : {} } catch { payload = { content: data } }
      switch (event) {
        case 'start':
          h.onStart?.({ request_id: String(payload.request_id ?? ''), session_id: String(payload.session_id ?? '') })
          break
        case 'message':
          h.onMessage(String(payload.content ?? ''))
          break
        case 'reasoning':
          h.onReasoning?.(String(payload.content ?? ''))
          break
        case 'retry':
        case 'parked':
        case 'upstream_status':
          h.onStatus?.({ kind: event, payload })
          break
        case 'error':
          h.onError?.(String(payload.message ?? payload.detail ?? '对话失败'))
          done = true
          break
        case 'done':
          h.onDone?.({ request_id: payload.request_id as string, session_id: payload.session_id as string })
          done = true
          break
        default:
          break
      }
    })
  }
}

export async function listChatSessions(): Promise<ChatSessionItem[]> {
  const servers = useServersStore()
  const r = await authedFetch(`${servers.apiBase}/console/chat/sessions`)
  if (!r.ok) return []
  const body = await r.json().catch(() => null)
  const rows = body?.data?.sessions ?? body?.sessions ?? body?.data ?? []
  if (!Array.isArray(rows)) return []
  // 契约归一：服务端摘要字段是 id（console.get_chat_sessions），统一映射为 session_id，
  // 消费方（ChatView 过滤/展示）只认 session_id——在边界修，不在下游补判
  return rows
    .map((row) => {
      const item = row as Record<string, unknown>
      return {
        session_id: String(item.session_id ?? item.id ?? ''),
        agent_id: item.agent_id as string | undefined,
        title: item.title as string | undefined,
        updated_at: item.updated_at as string | undefined,
      }
    })
    .filter((s) => !!s.session_id)
}

export async function fetchChatHistory(sessionId: string): Promise<Array<{ role: string; content: string }>> {
  const servers = useServersStore()
  const r = await authedFetch(`${servers.apiBase}/chat/history?session_id=${encodeURIComponent(sessionId)}`)
  if (!r.ok) return []
  const body = await r.json().catch(() => null)
  const rows = body?.data?.messages ?? body?.data ?? body?.messages ?? []
  return Array.isArray(rows) ? (rows as Array<{ role: string; content: string }>) : []
}
