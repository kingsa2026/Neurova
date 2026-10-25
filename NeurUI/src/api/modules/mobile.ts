import api, { request } from '@/api'
import type { ApiResponse } from '@/types/response'
import type { PairingCodeState, DeviceRegistryState, TunnelState, AddressSource }
  from '@/api/contracts/pairingStates'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PairingCode {
  code: string
  /** 进二维码的高熵一次性引用；与 `code` 同属一条配对记录的两个入口，不是两个凭据 */
  ref: string
  qr_code_url: string
  expires_in: number
  pairing_id: string
}

export interface PairedDevice {
  pairing_id: string
  device_name: string
  device_type: string
  device_id?: string
  paired_at: number
  last_active?: number
  is_online: boolean
  /** M1b 的投影态（`paired|online|offline|dormant|revoked`），字面量单源见 contracts */
  state?: DeviceRegistryState
  /** 长期在册的提醒位：满 30 天无活动只提示，系统不代删 */
  dormant?: boolean
}

export interface PairingStatus {
  code: string
  /** 后端回的是同一批词；类型收成契约那一份，不在此重列（教义第 6 条） */
  status: PairingCodeState
  device_name?: string
  confirmed_at?: number
}

/** 通道读数（`GET /mobile/pairing/tunnel/status`）——面板徽标的唯一来源 */
export interface TunnelStatus {
  state: TunnelState
  configured: boolean
  route_id?: string | null
  instance_id?: string
  last_heartbeat_at?: number | null
  last_rtt_ms?: number | null
  active_streams: number
  /** 与隧道态可并存：本次发码实际用哪条地址来源 */
  address_source: AddressSource
  last_error?: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/mobile'

/** Generate a pairing code and QR code. */
export function generatePairing(data: { device_name?: string; device_type?: string }) {
  return api.post<ApiResponse<PairingCode>>(`${BASE}/pairing/generate`, data)
}

/** 通道状态（面板据此决定能不能发码；读不到就如实显示"不知道"）。 */
export function getTunnelStatus() {
  return api.get<ApiResponse<TunnelStatus>>(`${BASE}/pairing/tunnel/status`)
}

/** 主动撤回一张还没被扫的码（误扫/换码不必干等 300 秒）。 */
export function cancelPairing(code: string) {
  return api.post<ApiResponse<{ status: string }>>(`${BASE}/pairing/cancel`, { code })
}

/** Get pairing status by code. */
export function getPairingStatus(code: string) {
  return api.get<ApiResponse<PairingStatus>>(`${BASE}/pairing/status/${code}`)
}

/**
 * 取那张配对二维码的**图字节**（不是 URL 字符串）。
 *
 * 为什么不直接把 `qr_code_url` 塞进 `<img src>`：后端那一口在 §6-172 批 28 上了登录门
 * （匿名按码回 200/404 ＝ 6 位配对码的枚举预言机），而 `<img>` 发不出 Authorization 头。
 * 于是走带凭证的 blob 取图（渠道扫码那形早就是这么给 base64 的），所有权归调用方释放。
 */
export function getPairingQrcodeBlob(code: string) {
  return request.get(`${BASE}/pairing/qrcode/${code}`,
    { responseType: 'blob' }) as unknown as Promise<Blob>
}

/** List paired devices. */
export function getPairedDevices() {
  return api.get<ApiResponse<{ devices: PairedDevice[]; total: number }>>(`${BASE}/pairing/list`)
}

/** Revoke a pairing. */
export function revokePairing(pairingId: string) {
  return api.delete<ApiResponse<{ message: string }>>(`${BASE}/pairing/${pairingId}`)
}
