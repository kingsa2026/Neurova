import { request } from '@/api'

// ============================================================
// 类型定义
// ============================================================

export interface GeneratePairingResponse {
  pairing_id: string
  code: string
  qr_data: string
  expires_at: number
  status: string
}

export interface ConfirmPairingRequest {
  code: string
  device_name?: string
  device_os?: string
}

export interface ConfirmPairingResponse {
  success: boolean
  pairing_id: string
  ws_token: string
  user_id: string
  agent_id: string
  error_message: string
}

export interface PairingStatusResponse {
  code: string
  status: 'pending' | 'confirmed' | 'revoked' | 'expired'
  pairing_id: string
  device_info: Record<string, unknown>
  expires_at: number
}

export interface PairedDevice {
  pairing_id: string
  device_info: Record<string, unknown>
  agent_id: string
  confirmed_at: number | null
}

// ============================================================
// API 方法
// ============================================================

export const mobilePairingAPI = {
  /** 生成配对码 + 二维码（需 JWT 认证） */
  generate: (agentId: string = 'Yiling') =>
    request.post<GeneratePairingResponse>('/mobile/pairing/generate', {
      agent_id: agentId,
    }),

  /** 获取配对二维码图片 */
  getQRCodeImage: (code: string) =>
    `/api/v1/mobile/pairing/qrcode/${code}`,

  /** 手机端确认配对（无需 JWT） */
  confirm: (data: ConfirmPairingRequest) =>
    request.post<ConfirmPairingResponse>('/mobile/pairing/confirm', data),

  /** 轮询配对状态（无需 JWT） */
  getStatus: (code: string) =>
    request.get<PairingStatusResponse>(`/mobile/pairing/status/${code}`),

  /** 列出已配对设备（需 JWT，用户隔离） */
  listDevices: () =>
    request.get<PairedDevice[]>('/mobile/pairing/list'),

  /** 解除配对（需 JWT，用户隔离） */
  revoke: (pairingId: string) =>
    request.delete(`/mobile/pairing/${pairingId}`),

  /** 构建 WebSocket URL */
  buildWsUrl: (host: string, port: number = 9527) =>
    `ws://${host}:${port}/api/v1/mobile/ws`,
}
