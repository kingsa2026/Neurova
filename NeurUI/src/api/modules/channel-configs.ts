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

/** P0-5 入站持久化队列统计（重启不丢消息的健康面）。 */
export interface ChannelIngressStats {
  enabled: boolean
  pending?: number
  processing?: number
  dead_letter?: number
  processed_total?: number
  error?: string
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

/** P0-5：入站持久化队列状态（裸对象，无信封）。 */
export function getIngressStats() {
  return api.get<ChannelIngressStats>(`${BASE}/ingress/stats`)
}

// ---------------------------------------------------------------------------
// B4-a 渠道管理能力面（restart / clear-queue / conflict-check）
// ---------------------------------------------------------------------------

/** 重启渠道适配器（disconnect → connect，配置变更生效/断线重连）。 */
export function restartChannelAdapter(type: string) {
  return api.post<{ code: number; message: string; data: { success: boolean; error?: string } }>(
    `/channel-adapters/${type}/restart`,
  )
}

/** 清空渠道待处理入站队列（积压清理）。 */
export function clearChannelQueue(type: string) {
  return api.post<{ code: number; message: string; data: { cleared: number } }>(
    `/channel-adapters/${type}/clear-queue`,
  )
}

/** 机器人身份冲突检测（多渠道复用同一凭据）。 */
export function checkChannelConflicts() {
  return api.get<{ code: number; message: string; data: { conflicts: { identity: string; channels: string[] }[]; checked: number } }>(
    `/channel-adapters/conflicts/check`,
  )
}

/** 插件渠道动态表单 schema（B4-d；未注册插件时为空数组）。 */
export function listPluginChannelSchemas() {
  return api.get<{ code: number; message: string; data: { schemas: { channel_type: string; name: string; config_fields: { key: string; label?: string; type: string; required?: boolean; default?: unknown; placeholder?: string }[] }[] } }>(
    `/channel-configs/schemas`,
  )
}
