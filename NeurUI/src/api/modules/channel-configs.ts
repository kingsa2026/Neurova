import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ChannelConfig {
  channel_type: string
  enabled: boolean
  connected?: boolean
  app_id?: string
  app_secret?: string
  use_stream?: boolean
  webhook_url?: string
  webhook_token?: string
  encrypt_key?: string
  verification_token?: string
  extra?: Record<string, unknown>
}

export interface ChannelConfigTestResult {
  success: boolean
  message?: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/channel-configs'

/** List all channel configurations. */
export function listChannelConfigs() {
  return api.get<ApiResponse<ChannelConfig[]>>(`${BASE}`)
}

/** Create or update a channel configuration. */
export function createChannelConfig(data: ChannelConfig) {
  return api.post<ApiResponse<{ success: boolean }>>(`${BASE}`, data)
}

/** Test a channel configuration. */
export function testChannelConfig(type: string, data: ChannelConfig) {
  return api.post<ApiResponse<ChannelConfigTestResult>>(`${BASE}/${type}/test`, data)
}
