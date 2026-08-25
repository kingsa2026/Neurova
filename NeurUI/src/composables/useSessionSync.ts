import { onBeforeUnmount, watch } from 'vue'

/**
 * 会话实时事件订阅（WebSocket /api/v1/sync/ws/{session_id}）
 *
 * 用途：接收蜂群子 Agent 事件（subagent_started/chunk/completed），
 * 驱动聊天页的子 Agent 对话小窗。
 *
 * - sessionId 变化时自动重连；为空时不连接
 * - channel_type 携带标签页唯一后缀，避免多标签互顶（UnifiedSession 按
 *   channel_type 去重）
 * - 断线自动重连（指数退避，上限 10s）；组件卸载时清理
 */
export interface SessionSyncEvent {
  event_id: string
  event_type: string
  session_id: string
  source_channel: string
  timestamp: string
  payload: Record<string, unknown>
}

export interface SessionSyncHandle {
  close: () => void
}

export function useSessionSync(
  getSessionId: () => string | null | undefined,
  onEvent: (event: SessionSyncEvent) => void,
): SessionSyncHandle {
  let ws: WebSocket | null = null
  let closed = false
  let retry = 0
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let currentSession = ''
  // 每个标签页唯一渠道名，避免同页多实例互顶
  const channelType = `web-chat-${Math.random().toString(36).slice(2, 10)}`

  function buildUrl(sessionId: string): string {
    const base = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    const wsBase = base.replace(/^http/, 'ws')
    return `${wsBase}/sync/ws/${encodeURIComponent(sessionId)}?channel_type=${channelType}`
  }

  function connect(sessionId: string) {
    if (closed) return
    try {
      ws = new WebSocket(buildUrl(sessionId))
    } catch {
      scheduleReconnect(sessionId)
      return
    }

    ws.onmessage = evt => {
      try {
        const event = JSON.parse(evt.data as string) as SessionSyncEvent
        if (event?.event_type) onEvent(event)
      } catch {
        // 非 JSON 帧（如 ack）忽略
      }
    }

    ws.onclose = () => {
      if (!closed && currentSession === sessionId) scheduleReconnect(sessionId)
    }

    ws.onerror = () => {
      ws?.close()
    }
  }

  function scheduleReconnect(sessionId: string) {
    if (closed) return
    retry += 1
    const delay = Math.min(1000 * 2 ** Math.min(retry, 4), 10_000)
    reconnectTimer = setTimeout(() => connect(sessionId), delay)
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      closed = true
      ws.close()
      ws = null
    }
  }

  watch(
    () => getSessionId(),
    sessionId => {
      const sid = sessionId || ''
      if (sid === currentSession) return
      disconnect()
      closed = false
      retry = 0
      currentSession = sid
      if (sid) connect(sid)
    },
    { immediate: true },
  )

  onBeforeUnmount(disconnect)

  return { close: disconnect }
}
