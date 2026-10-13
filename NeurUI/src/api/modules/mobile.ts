import api, { request } from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PairingCode {
  code: string
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
}

export interface PairingStatus {
  code: string
  status: 'pending' | 'confirmed' | 'expired' | 'revoked'
  device_name?: string
  confirmed_at?: number
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/mobile'

/** Generate a pairing code and QR code. */
export function generatePairing(data: { device_name?: string; device_type?: string }) {
  return api.post<ApiResponse<PairingCode>>(`${BASE}/pairing/generate`, data)
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
