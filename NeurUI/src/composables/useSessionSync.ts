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
 * - seq/gap 检测（OpenOcta 启发 P0-1）：服务端每个事件帧带 per-session
 *   单调 seq；本组合式函数维护游标 lastSeq，检测跳号触发 onGap 并请求
 *   定向补发（sync_resume），旧帧去重，服务端纪元更迭（后端重启）自动
 *   重置游标避免误吞新帧
 */
export interface SessionSyncEvent {
  event_id: string
  event_type: string
  session_id: string
  source_channel: string
  timestamp: string
  payload: Record<string, unknown>
  /** 服务端 per-session 单调序号（session_sync_manager 盖章）；控制帧无此字段 */
  seq?: number
}

export interface SessionSyncHandle {
  close: () => void
}

export interface SessionSyncOptions {
  /** 检测到事件缺口（seq 跳号）时回调：missed=丢失帧数，lastSeq=最后连续序号 */
  onGap?: (missed: number, lastSeq: number) => void
}

export function useSessionSync(
  getSessionId: () => string | null | undefined,
  onEvent: (event: SessionSyncEvent) => void,
  options: SessionSyncOptions = {},
): SessionSyncHandle {
  let ws: WebSocket | null = null
  let closed = false
  let retry = 0
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let currentSession = ''
  // 每个标签页唯一渠道名，避免同页多实例互顶
  const channelType = `web-chat-${Math.random().toString(36).slice(2, 10)}`
  // seq 游标（本会话已见最大序号）。重连保留（供 sync_resume 定向补发与
  // 旧帧去重）；会话切换清零；sync_hello 纪元更迭时清零
  let lastSeq: number | null = null

  function buildUrl(sessionId: string): string {
    const base = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    const wsBase = base.replace(/^http/, 'ws')
    return `${wsBase}/sync/ws/${encodeURIComponent(sessionId)}?channel_type=${channelType}`
  }

  function handleSeqFrame(event: SessionSyncEvent): boolean {
    const seq = event.seq
    if (typeof seq !== 'number') return true
    if (lastSeq !== null && seq > lastSeq + 1) {
      // 缺口：丢帧数 = seq - lastSeq - 1。事件仍投递（有总比没有强），
      // 补发请求交给重连 sync_resume 通道
      options.onGap?.(seq - lastSeq - 1, lastSeq)
    }
    if (lastSeq !== null && seq <= lastSeq) {
      // 本连接内重复/重放旧帧：去重跳过
      return false
    }
    lastSeq = seq
    return true
  }

  function connect(sessionId: string) {
    if (closed) return
    try {
      ws = new WebSocket(buildUrl(sessionId))
    } catch {
      scheduleReconnect(sessionId)
      return
    }

    ws.onopen = () => {
      // 重连时携带游标请求定向补发（首次连接游标为空，服务端自动重放
      // 最近历史作为基线）
      if (lastSeq !== null && ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'sync_resume', last_seq: lastSeq }))
      }
    }

    ws.onmessage = evt => {
      try {
        const event = JSON.parse(evt.data as string) as SessionSyncEvent & {
          type?: string
          next_seq?: number
        }
        // 纪元探测帧：服务端当前发号器落后于本地游标 → 后端已重启（seq
        // 归零），重置游标，否则新帧会被当作旧帧全部误吞
        if (event.type === 'sync_hello' && typeof event.next_seq === 'number') {
          if (lastSeq !== null && event.next_seq <= lastSeq) lastSeq = null
          return
        }
        if (event.type === 'sync_resume_done') return
        if (event?.event_type && handleSeqFrame(event)) onEvent(event)
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
      lastSeq = null // 会话切换：新事件流，游标清零
      if (sid) connect(sid)
    },
    { immediate: true },
  )

  onBeforeUnmount(disconnect)

  return { close: disconnect }
}
