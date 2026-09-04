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
 * - gap 自愈（OpenClaw 启发 P0-7 慢消费者配套）：检测到缺口立即重连，
 *   服务端把丢帧留在历史中（丢帧也推进 seq），重连时以最早缺口的前一
 *   序号作为 sync_resume 游标整段重放；缺口区间内的重放帧回填投递，
 *   区间外已见帧去重——幂等投影合并，中间丢帧不再永久缺失
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
  // 本连接内未回填的缺口区间 [low, high]（升序发现）。重连时以最早缺口
  // 的前一序号作为 resume 游标；区间内的重放帧回填，区间外去重
  let gapRanges: Array<[number, number]> = []
  let resyncing = false

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
      // 并记录缺口区间触发重连自愈（服务端丢帧留在历史，重连整段重放）
      options.onGap?.(seq - lastSeq - 1, lastSeq)
      gapRanges.push([lastSeq + 1, seq - 1])
      triggerResync()
    }
    if (lastSeq !== null && seq <= lastSeq) {
      // 本连接内重复/重放旧帧：缺口区间内的回填投递，区间外去重跳过
      return consumeGap(seq)
    }
    lastSeq = seq
    return true
  }

  /** 旧帧是否落在缺口区间内（回填投递并收缩区间）；区间外去重返回 false */
  function consumeGap(seq: number): boolean {
    for (let i = 0; i < gapRanges.length; i++) {
      const [low, high] = gapRanges[i]
      if (seq < low || seq > high) continue
      if (seq === low) {
        // 重放按序到达：从左端收缩，空区间移除
        if (low === high) gapRanges.splice(i, 1)
        else gapRanges[i] = [low + 1, high]
      }
      return true
    }
    return false
  }

  /** gap 自愈：立即重连走 onopen 的 sync_resume 整段重放（最快退避） */
  function triggerResync() {
    if (resyncing || closed || !ws) return
    resyncing = true
    retry = 0
    ws.close() // onclose → scheduleReconnect
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
      resyncing = false
      // 重连时携带游标请求定向补发（首次连接游标为空，服务端自动重放
      // 最近历史作为基线）。有未回填缺口时从缺口起点整段重放：已见帧
      // 被去重/区间回填，幂等无副作用
      if (ws && ws.readyState === WebSocket.OPEN) {
        const resumeFrom = gapRanges.length ? gapRanges[0][0] - 1 : lastSeq
        if (resumeFrom !== null) {
          ws.send(JSON.stringify({ type: 'sync_resume', last_seq: resumeFrom }))
        }
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
          if (lastSeq !== null && event.next_seq <= lastSeq) {
            lastSeq = null
            gapRanges = []
          }
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
      gapRanges = []
      if (sid) connect(sid)
    },
    { immediate: true },
  )

  onBeforeUnmount(disconnect)

  return { close: disconnect }
}
