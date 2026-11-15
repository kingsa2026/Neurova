/**
 * 移动 WS 通道适配器（设计方案 M3 设备连接会话状态机）。
 *
 * - 握手：一次性 connect_ticket 走 Sec-WebSocket-Protocol 子协议
 *   `neurova.auth.<ticket>`（浏览器 WS 无法设 Authorization 头，服务端两条都支持）。
 * - 心跳 30s ping/pong；pong 超时视为断流（中继上静默断流没有 close 帧）。
 * - 关闭码分档：4001 且本地 ticket 未过期 → 先 refresh 续签重试一次；
 *   refresh 也被拒（设备已解除）→ failed(device_deregistered)，唯一需要重新配对的路径。
 *   4008（单用户连接超限）→ 不重连。
 * - closed(manual) 为终态，不得被 reconnecting 覆盖（设计方案 §5.3 真竞态）。
 */
import { refreshPairingTicket } from '@/api/pairing'
import { usePairingStore } from '@/stores/pairing'

export type WsState =
  | 'idle'
  | 'reauthing'
  | 'connecting'
  | 'authed'
  | 'streaming'
  | 'reconnecting'
  | 'failed'
  | 'closed'

export interface WsHandlers {
  onState?: (state: WsState, detail?: string) => void
  onChunk?: (content: string, sessionId: string) => void
  onDone?: (sessionId: string) => void
  onCancelled?: (sessionId: string) => void
  onError?: (code: string, message: string) => void
  onAgentSwitched?: (agentId: string) => void
}

const MAX_RECONNECT = 10
const HEARTBEAT_MS = 30000
const PONG_TIMEOUT_MS = 10000

export class MobileWsChannel {
  private ws: WebSocket | null = null
  private state: WsState = 'idle'
  private heartbeatTimer: number | null = null
  private pongTimer: number | null = null
  private reconnectTimer: number | null = null
  private reconnectCount = 0
  private manualClosed = false
  private currentSessionId = ''
  private handlers: WsHandlers = {}

  constructor(private wsUrl: string) {}

  private setState(s: WsState, detail?: string) {
    this.state = s
    this.handlers.onState?.(s, detail)
  }

  getState(): WsState {
    return this.state
  }

  /** 建连：ticket 从配对仓取；过期先走 refresh 续签（reauthing） */
  async connect(handlers: WsHandlers): Promise<boolean> {
    this.handlers = handlers
    this.manualClosed = false
    const pairing = usePairingStore()
    if (!pairing.paired) {
      this.setState('failed', 'device_not_paired')
      return false
    }
    let ticket = pairing.ticket
    if (!ticket || pairing.ticketExpiresAt < Date.now() + 5000) {
      this.setState('reauthing')
      try {
        const refreshed = await refreshPairingTicket(
          pairing.pairingId,
          pairing.deviceSecret,
          crypto.randomUUID(),
        )
        await pairing.applyRefreshed(refreshed.connectTicket, refreshed.expiresIn)
        ticket = refreshed.connectTicket
      } catch {
        this.setState('failed', 'device_deregistered')
        return false
      }
    }
    return this.openSocket(ticket)
  }

  private openSocket(ticket: string): Promise<boolean> {
    return new Promise((resolve) => {
      this.setState('connecting')
      // 浏览器 WS 不能设 Authorization 头 → 走 Sec-WebSocket-Protocol 子协议通道
      const ws = new WebSocket(this.wsUrl, [`neurova.auth.${ticket}`])
      this.ws = ws

      const timeout = window.setTimeout(() => {
        if (this.state === 'connecting') {
          ws.close()
          resolve(this.handleConnectFailure('connect_timeout'))
        }
      }, 12000)

      ws.onopen = () => {
        window.clearTimeout(timeout)
        this.reconnectCount = 0
        this.setState('authed')
        this.startHeartbeat()
        resolve(true)
      }
      ws.onmessage = (ev) => this.handleMessage(ev.data)
      ws.onclose = (ev) => {
        window.clearTimeout(timeout)
        this.stopHeartbeat()
        if (this.manualClosed) {
          this.setState('closed')
          resolve(false)
          return
        }
        resolve(this.handleClose(ev.code))
      }
      ws.onerror = () => {
        // onclose 会随后到达，统一在 close 里处置
      }
    })
  }

  private handleConnectFailure(reason: string): boolean {
    this.reconnectCount += 1
    if (this.reconnectCount >= MAX_RECONNECT) {
      this.setState('failed', 'max_reconnect_exhausted')
      return false
    }
    this.setState('reconnecting', `${reason} (${this.reconnectCount}/${MAX_RECONNECT})`)
    return false
  }

  private handleClose(code: number): boolean {
    if (this.manualClosed) {
      this.setState('closed')
      return false
    }
    if (code === 4008) {
      // 单用户连接超限：重连只会继续撞墙，直接失败并提示
      this.setState('failed', 'too_many_connections')
      return false
    }
    if (code === 4001) {
      // 凭证失效：先续签重试一次；设备被解除时 refresh 会拒绝 → 唯一重扫路径
      this.setState('reauthing')
      this.reconnect().then((ok) => {
        if (!ok) this.setState('failed', 'device_deregistered')
      })
      return false
    }
    return this.handleConnectFailure(`close_${code}`)
  }

  private async reconnect(): Promise<boolean> {
    const pairing = usePairingStore()
    try {
      const refreshed = await refreshPairingTicket(
        pairing.pairingId,
        pairing.deviceSecret,
        crypto.randomUUID(),
      )
      await pairing.applyRefreshed(refreshed.connectTicket, refreshed.expiresIn)
      return await this.openSocket(refreshed.connectTicket)
    } catch {
      return false
    }
  }

  private startHeartbeat() {
    this.stopHeartbeat()
    this.heartbeatTimer = window.setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }))
        this.pongTimer = window.setTimeout(() => {
          // pong 超时：中继静默断流不会有 close 帧，主动判死重连
          this.ws?.close()
        }, PONG_TIMEOUT_MS)
      }
    }, HEARTBEAT_MS)
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer) window.clearInterval(this.heartbeatTimer)
    if (this.pongTimer) window.clearTimeout(this.pongTimer)
    this.heartbeatTimer = null
    this.pongTimer = null
  }

  private handleMessage(raw: string) {
    let msg: Record<string, unknown> = {}
    try {
      msg = JSON.parse(raw)
    } catch {
      return
    }
    switch (msg.type) {
      case 'pong':
        if (this.pongTimer) window.clearTimeout(this.pongTimer)
        break
      case 'chat:chunk':
        this.setState('streaming')
        this.handlers.onChunk?.(String(msg.content ?? ''), String(msg.session_id ?? ''))
        break
      case 'chat:done':
        this.setState('authed')
        this.handlers.onDone?.(String(msg.session_id ?? ''))
        break
      case 'chat:cancelled':
        this.setState('authed')
        this.handlers.onCancelled?.(String(msg.session_id ?? ''))
        break
      case 'agent:switched':
        this.handlers.onAgentSwitched?.(String(msg.agent_id ?? ''))
        break
      case 'error':
        this.handlers.onError?.(String(msg.code ?? 'error'), String(msg.message ?? ''))
        break
      default:
        break
    }
  }

  /** 发送一轮流式对话（同连接同时只允许一条在流回复——服务端契约） */
  sendChat(content: string, agentId: string, sessionId: string): boolean {
    if (this.state !== 'authed' && this.state !== 'streaming') return false
    if (this.state === 'streaming') return false
    this.currentSessionId = sessionId
    this.ws?.send(
      JSON.stringify({ type: 'chat:send', content, agent_id: agentId, session_id: sessionId }),
    )
    return true
  }

  cancelChat(): void {
    if (this.currentSessionId) {
      this.ws?.send(JSON.stringify({ type: 'chat:cancel', session_id: this.currentSessionId }))
    }
  }

  /** 主动断开（终态 closed，不得被重连覆盖） */
  close(): void {
    this.manualClosed = true
    if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer)
    this.stopHeartbeat()
    this.ws?.close()
    this.ws = null
    this.setState('closed')
  }
}
