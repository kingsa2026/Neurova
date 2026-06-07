/**
 * 会话同步 API 模块
 *
 * 提供跨渠道会话同步的 API 接口和 WebSocket 连接管理。
 */

import request from '@/api/request'

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

/** 事件类型 */
export type EventType =
  | 'user_message'
  | 'agent_thinking'
  | 'agent_tool_call'
  | 'agent_tool_result'
  | 'agent_command'
  | 'agent_reply'
  | 'agent_error'
  | 'agent_stream_chunk'
  | 'session_created'
  | 'session_resumed'
  | 'session_paused'
  | 'session_ended'
  | 'channel_connected'
  | 'channel_disconnected'
  | 'heartbeat'

/** 会话事件 */
export interface SessionEvent {
  event_id: string
  event_type: EventType
  session_id: string
  source_channel: string
  timestamp: string
  payload: Record<string, any>
}

/** 会话信息 */
export interface SessionInfo {
  session_id: string
  user_id: string
  agent_id: string
  conversation_id: string
  created_at: string
  last_activity: string
  status: string
  active_channels: string[]
  history_size: number
}

/** 创建会话请求 */
export interface CreateSessionRequest {
  user_id: string
  agent_id?: string
  external_id?: string
  metadata?: Record<string, any>
}

/** 发送消息请求 */
export interface SendMessageRequest {
  content: string
  channel_type?: string
  metadata?: Record<string, any>
}

/** WebSocket 连接选项 */
export interface WebSocketOptions {
  session_id: string
  channel_type?: string
  onMessage?: (event: SessionEvent) => void
  onConnect?: () => void
  onDisconnect?: () => void
  onError?: (error: Event) => void
  autoReconnect?: boolean
  reconnectInterval?: number
}

// ---------------------------------------------------------------------------
// REST API
// ---------------------------------------------------------------------------

export const sessionSyncAPI = {
  /** 创建会话 */
  createSession: (data: CreateSessionRequest) =>
    request.post<SessionInfo>('/sync/sessions', data),

  /** 获取会话信息 */
  getSession: (sessionId: string) =>
    request.get<SessionInfo>(`/sync/sessions/${sessionId}`),

  /** 获取会话历史 */
  getHistory: (sessionId: string, limit: number = 100) =>
    request.get<{ session_id: string; total: number; events: SessionEvent[] }>(
      `/sync/sessions/${sessionId}/history`,
      { params: { limit } }
    ),

  /** 发送消息（REST 降级） */
  sendMessage: (sessionId: string, data: SendMessageRequest) =>
    request.post<{ success: boolean; event_id: string; sent_to_channels: number }>(
      `/sync/sessions/${sessionId}/messages`,
      data
    ),

  /** 结束会话 */
  endSession: (sessionId: string) =>
    request.delete(`/sync/sessions/${sessionId}`),

  /** 列出会话 */
  listSessions: (params?: { user_id?: string; agent_id?: string; status?: string }) =>
    request.get<{ total: number; sessions: SessionInfo[] }>('/sync/sessions', { params }),

  /** 获取统计信息 */
  getStatistics: () =>
    request.get<{
      total_sessions: number
      active_sessions: number
      total_channels: number
      user_mappings: number
      external_mappings: number
    }>('/sync/statistics'),

  /** 获取活跃连接 */
  getConnections: () =>
    request.get<{
      total: number
      connections: Array<{
        session_id: string
        connection_id: string
        channel_type: string
        connected_at: string
        last_heartbeat: string
      }>
    }>('/sync/connections'),
}

// ---------------------------------------------------------------------------
// WebSocket 管理器
// ---------------------------------------------------------------------------

export class SessionWebSocket {
  private ws: WebSocket | null = null
  private options: WebSocketOptions
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private isConnecting = false
  private isManualClose = false

  constructor(options: WebSocketOptions) {
    this.options = {
      channel_type: 'web',
      autoReconnect: true,
      reconnectInterval: 3000,
      ...options,
    }
  }

  /** 连接 WebSocket */
  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN || this.isConnecting) {
      return
    }

    this.isConnecting = true
    this.isManualClose = false

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const channelType = this.options.channel_type || 'web'
    const url = `${protocol}//${host}/api/v1/sync/ws/${this.options.session_id}?channel_type=${channelType}`

    try {
      this.ws = new WebSocket(url)

      this.ws.onopen = () => {
        console.log('[SessionSync] WebSocket connected')
        this.isConnecting = false
        this.startHeartbeat()
        this.options.onConnect?.()
      }

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)

          // 处理心跳响应
          if (data.type === 'heartbeat_ack') {
            return
          }

          // 处理同步响应
          if (data.type === 'sync_response') {
            // 可以在这里处理历史数据
            return
          }

          // 处理消息确认
          if (data.type === 'message_sent') {
            return
          }

          // 处理会话事件
          const sessionEvent = data as SessionEvent
          this.options.onMessage?.(sessionEvent)
        } catch (e) {
          console.error('[SessionSync] Failed to parse message:', e)
        }
      }

      this.ws.onclose = (event) => {
        console.log('[SessionSync] WebSocket closed:', event.code, event.reason)
        this.isConnecting = false
        this.stopHeartbeat()
        this.options.onDisconnect?.()

        // 自动重连
        if (!this.isManualClose && this.options.autoReconnect) {
          this.scheduleReconnect()
        }
      }

      this.ws.onerror = (event) => {
        console.error('[SessionSync] WebSocket error:', event)
        this.options.onError?.(event)
      }
    } catch (e) {
      console.error('[SessionSync] Failed to create WebSocket:', e)
      this.isConnecting = false
      this.scheduleReconnect()
    }
  }

  /** 断开连接 */
  disconnect(): void {
    this.isManualClose = true
    this.stopHeartbeat()
    this.clearReconnectTimer()

    if (this.ws) {
      this.ws.close(1000, 'Manual close')
      this.ws = null
    }
  }

  /** 发送消息 */
  sendMessage(content: string, metadata?: Record<string, any>): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket is not connected')
    }

    this.ws.send(
      JSON.stringify({
        type: 'user_message',
        content,
        metadata: metadata || {},
      })
    )
  }

  /** 请求同步历史 */
  requestSync(limit: number = 100): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return
    }

    this.ws.send(
      JSON.stringify({
        type: 'sync_request',
        limit,
      })
    )
  }

  /** 是否已连接 */
  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  /** 开始心跳 */
  private startHeartbeat(): void {
    this.stopHeartbeat()
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'heartbeat' }))
      }
    }, 30000) // 每 30 秒发送心跳
  }

  /** 停止心跳 */
  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  /** 安排重连 */
  private scheduleReconnect(): void {
    this.clearReconnectTimer()
    this.reconnectTimer = setTimeout(() => {
      console.log('[SessionSync] Attempting to reconnect...')
      this.connect()
    }, this.options.reconnectInterval)
  }

  /** 清除重连定时器 */
  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }
}

// ---------------------------------------------------------------------------
// Composable 工厂函数
// ---------------------------------------------------------------------------

/**
 * 创建会话同步 WebSocket 连接
 *
 * 使用示例：
 * ```typescript
 * const ws = createSessionWebSocket({
 *   sessionId: 'session_xxx',
 *   onMessage: (event) => {
 *     // 处理事件
 *   }
 * })
 *
 * ws.connect()
 * ```
 */
export function createSessionWebSocket(options: {
  sessionId: string
  channelType?: string
  onMessage?: (event: SessionEvent) => void
  onConnect?: () => void
  onDisconnect?: () => void
  onError?: (error: Event) => void
  autoReconnect?: boolean
}): SessionWebSocket {
  return new SessionWebSocket({
    session_id: options.sessionId,
    channel_type: options.channelType,
    onMessage: options.onMessage,
    onConnect: options.onConnect,
    onDisconnect: options.onDisconnect,
    onError: options.onError,
    autoReconnect: options.autoReconnect,
  })
}
