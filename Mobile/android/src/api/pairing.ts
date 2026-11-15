/** 配对 API（设计方案 §3.4/§5.3）：resolve 换回连地址 → confirm 拿设备身份与一次性票据 */
import { apiPost } from '@/utils/http'

export interface PairingResolved {
  wsUrl: string
  pairingId: string
  expiresIn: number
  status: string
}

export interface PairingConfirmed {
  wsToken: string
  wsUrl: string
  expiresIn: number
  deviceSecret?: string
  pairingId?: string
}

export interface PairingRefreshed {
  connectTicket: string
  pairingId: string
  expiresIn: number
}

export async function resolvePairing(ref: string): Promise<PairingResolved> {
  return apiPost<PairingResolved>('/mobile/pairing/resolve', { ref })
}

export async function confirmPairingByRef(ref: string, deviceName: string): Promise<PairingConfirmed> {
  return apiPost<PairingConfirmed>('/mobile/pairing/confirm', {
    ref,
    deviceName,
    deviceType: 'android',
  })
}

export async function refreshPairingTicket(
  pairingId: string,
  deviceSecret: string,
  challenge: string,
): Promise<PairingRefreshed> {
  return apiPost<PairingRefreshed>('/mobile/pairing/refresh', {
    pairing_id: pairingId,
    device_secret: deviceSecret,
    challenge,
  })
}
