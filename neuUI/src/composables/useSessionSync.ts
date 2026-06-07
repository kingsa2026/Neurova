/**
 * 会话同步 Composable
 *
 * 提供响应式的会话同步状态管理。
 */

import { ref, onUnmounted, watch, type Ref } from 'vue'
import {
  sessionSyncAPI,
  SessionWebSocket,
  type SessionEvent,
  type SessionInfo,
  type EventType,
} from '@/api/modules/session-sync'

export interface UseSessionSyncOptions {
  /** 用户 ID */
  userId: string
  /** Agent ID */
  agentId?: string
  /** 渠道类型 */
  channelType?: string
  /** 自动连接 */
  autoConnect?: boolean
  /** 事件过滤器 */
  eventFilter?: EventType[]
}

export interface UseSessionSyncReturn {
  /** 会话信息 */
  session: Ref<SessionInfo | null>
  /** 事件列表 */
  events: Ref<SessionEvent[]>
  /** 连接状态 */
  isConnected: Ref<boolean>
  /** 加载状态 */
  loading: Ref<boolean>
  /** 错误信息 */
  error: Ref<string | null>
  /** 连接 */
  connect: () => Promise<void>
  /** 断开连接 */
  disconnect: () => void
  /** 发送消息 */
  sendMessage: (content: string, metadata?: Record<string, any>) => void
  /** 加载历史 */
  loadHistory: (limit?: number) => Promise<void>
  /** 清空事件 */
  clearEvents: () => void
}

/**
 * 使用会话同步
 *
 * 使用示例：
 * ```typescript
 * const { session, events, isConnected, sendMessage } = useSessionSync({
 *   userId: 'user_123',
 *   agentId: 'agent_456',
 *   onEvent: (event) => {
 *     console.log('New event:', event)
 *   }
 * })
 * ```
 */
export function useSessionSync(options: UseSessionSyncOptions): UseSessionSyncReturn {
  const {
    userId,
    agentId = 'default',
    channelType = 'web',
    autoConnect = true,
    eventFilter,
  } = options

  const session = ref<SessionInfo | null>(null)
  const events = ref<SessionEvent[]>([])
  const isConnected = ref(false)
  const loading = ref(false)
  const error = ref<string | null>(null)

  let ws: SessionWebSocket | null = null

  /** 处理接收到的事件 */
  function handleEvent(event: SessionEvent) {
    // 应用事件过滤器
    if (eventFilter && !eventFilter.includes(event.event_type)) {
      return
    }

    // 添加到事件列表
    events.value.push(event)

    // 限制事件数量
    if (events.value.length > 1000) {
      events.value = events.value.slice(-500)
    }
  }

  /** 创建或获取会话 */
  async function ensureSession(): Promise<SessionInfo> {
    if (session.value) {
      return session.value
    }

    loading.value = true
    error.value = null

    try {
      // 尝试获取现有会话
      const listRes = await sessionSyncAPI.listSessions({
        user_id: userId,
        agent_id: agentId,
        status: 'active',
      })

      if (listRes.data.sessions.length > 0) {
        session.value = listRes.data.sessions[0]
        return session.value
      }

      // 创建新会话
      const createRes = await sessionSyncAPI.createSession({
        user_id: userId,
        agent_id: agentId,
      })

      session.value = createRes.data
      return session.value
    } catch (e: any) {
      error.value = e.message || 'Failed to create session'
      throw e
    } finally {
      loading.value = false
    }
  }

  /** 连接 WebSocket */
  async function connect() {
    try {
      const sess = await ensureSession()

      ws = new SessionWebSocket({
        session_id: sess.session_id,
        channel_type: channelType,
        onMessage: handleEvent,
        onConnect: () => {
          isConnected.value = true
          error.value = null
        },
        onDisconnect: () => {
          isConnected.value = false
        },
        onError: (e) => {
          error.value = 'WebSocket connection error'
        },
        autoReconnect: true,
      })

      ws.connect()
    } catch (e: any) {
      error.value = e.message || 'Failed to connect'
    }
  }

  /** 断开连接 */
  function disconnect() {
    if (ws) {
      ws.disconnect()
      ws = null
    }
    isConnected.value = false
  }

  /** 发送消息 */
  function sendMessage(content: string, metadata?: Record<string, any>) {
    if (!ws || !ws.isConnected) {
      // 降级到 REST API
      if (session.value) {
        sessionSyncAPI.sendMessage(session.value.session_id, {
          content,
          channel_type: channelType,
          metadata,
        })
      }
      return
    }

    ws.sendMessage(content, metadata)
  }

  /** 加载历史 */
  async function loadHistory(limit: number = 100) {
    if (!session.value) {
      await ensureSession()
    }

    if (!session.value) {
      return
    }

    loading.value = true

    try {
      const res = await sessionSyncAPI.getHistory(session.value.session_id, limit)
      events.value = res.data.events
    } catch (e: any) {
      error.value = e.message || 'Failed to load history'
    } finally {
      loading.value = false
    }
  }

  /** 清空事件 */
  function clearEvents() {
    events.value = []
  }

  // 自动连接
  if (autoConnect) {
    connect()
  }

  // 组件卸载时断开连接
  onUnmounted(() => {
    disconnect()
  })

  return {
    session,
    events,
    isConnected,
    loading,
    error,
    connect,
    disconnect,
    sendMessage,
    loadHistory,
    clearEvents,
  }
}
