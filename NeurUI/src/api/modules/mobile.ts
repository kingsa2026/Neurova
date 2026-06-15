import api from '@/api'
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

/** List paired devices. */
export function getPairedDevices() {
  return api.get<ApiResponse<{ devices: PairedDevice[]; total: number }>>(`${BASE}/pairing/list`)
}

/** Revoke a pairing. */
export function revokePairing(pairingId: string) {
  return api.delete<ApiResponse<{ message: string }>>(`${BASE}/pairing/${pairingId}`)
}
