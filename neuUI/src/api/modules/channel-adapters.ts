import { request } from '@/api'

// ============================================================
// 类型定义
// ============================================================

export interface ChannelStatusResponse {
  channel_type: string
  connected: boolean
  enabled: boolean
  extra: Record<string, unknown>
}

export interface ChannelListResponse {
  running: boolean
  adapters: Record<string, ChannelStatusResponse>
}

export interface SendMessageRequest {
  chat_id: string
  content: string
  message_type?: string
  extra?: Record<string, unknown>
}

export interface SendMessageResponse {
  success: boolean
  message_id?: string
  error?: string
}

export interface ConnectRequest {
  app_id?: string
  app_secret?: string
  use_stream?: boolean
  extra?: Record<string, unknown>
}

export interface WebhookConfigRequest {
  webhook_url?: string
  token?: string
  encrypt_key?: string
}

export interface HealthCheckItem {
  channel_type: string
  healthy: boolean
  latency_ms?: number
  error?: string
  checked_at: string
}

// ============================================================
// API 方法
// ============================================================

const BASE = '/channel-adapters/channels'

export const channelAdaptersAPI = {
  /** 列出所有渠道状态 */
  list: () =>
    request.get<ChannelListResponse>(BASE),

  /** 获取指定渠道状态 */
  getStatus: (channelType: string) =>
    request.get<ChannelStatusResponse>(`${BASE}/${encodeURIComponent(channelType)}`),

  /** 连接指定渠道 */
  connect: (channelType: string, data?: ConnectRequest) =>
    request.post<ChannelStatusResponse>(`${BASE}/${encodeURIComponent(channelType)}/connect`, data),

  /** 断开指定渠道 */
  disconnect: (channelType: string) =>
    request.post<ChannelStatusResponse>(`${BASE}/${encodeURIComponent(channelType)}/disconnect`),

  /** 发送消息 */
  send: (channelType: string, data: SendMessageRequest) =>
    request.post<SendMessageResponse>(`${BASE}/${encodeURIComponent(channelType)}/send`, data),

  /** Webhook 回调入口 */
  webhook: (channelType: string, data: unknown) =>
    request.post(`${BASE}/${encodeURIComponent(channelType)}/webhook`, data),

  /** 渠道健康检查 */
  healthAll: () =>
    request.get<HealthCheckItem[]>(`${BASE}/health/all`),
}

export default channelAdaptersAPI
