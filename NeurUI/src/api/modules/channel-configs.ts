import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ChannelConfig {
  channel_type: string
  /** agent 隔离多实例（2026-09-13）：配置归属 agent，缺省 default */
  agent_id?: string
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
  /** F-2：wechat iLink 无 token 时诚实失败并引导扫码 */
  needs_scan?: boolean
}

/** F-3：iLink 二维码生成响应（两段式·生成段，裸对象）。 */
export interface WechatIlinkQrcodeResponse {
  status: 'ready' | 'pending'
  qr_url?: string
  qr_id?: string
}

/** F-3：iLink 扫码状态（两段式·轮询段，单次查询，裸对象）。 */
export interface WechatIlinkQrcodeStatus {
  status: 'pending' | 'scanned' | 'confirmed' | 'expired'
  token_saved?: boolean
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

/** List channel configurations of an agent (default agent when omitted). */
export function listChannelConfigs(agentId?: string) {
  return api.get<ApiResponse<ChannelConfig[]>>(`${BASE}`, { params: agentId ? { agent_id: agentId } : {} })
}

/** Create or update a channel configuration of an agent. */
export function createChannelConfig(data: ChannelConfig, agentId?: string) {
  return api.post<ApiResponse<{ success: boolean; needs_scan?: boolean }>>(
    `${BASE}`, data, { params: agentId ? { agent_id: agentId } : {} },
  )
}

/** Delete a channel configuration of an agent (unregisters adapter too). */
export function deleteChannelConfig(type: string, agentId?: string) {
  return api.delete<ApiResponse<unknown>>(`${BASE}/${type}`, {
    params: agentId ? { agent_id: agentId } : {},
  })
}

/** Test a channel configuration. */
export function testChannelConfig(type: string, data: ChannelConfig, agentId?: string) {
  return api.post<ApiResponse<ChannelConfigTestResult>>(
    `${BASE}/${type}/test`, data, { params: agentId ? { agent_id: agentId } : {} },
  )
}

/** F-3：生成 iLink 登录二维码（后端只生成不等待；已有有效 token 返回 ready）。 */
export function createWechatIlinkQrcode(data?: { token_file?: string; bot_token?: string }, agentId?: string) {
  return api.post<WechatIlinkQrcodeResponse>(
    `${BASE}/wechat/ilink/qrcode`, data ?? {}, { params: agentId ? { agent_id: agentId } : {} },
  )
}

/** F-3：单次查询 iLink 扫码状态（轮询节奏由前端驱动，3s/次）。 */
export function getWechatIlinkQrcodeStatus(qrId: string, agentId?: string) {
  return api.get<WechatIlinkQrcodeStatus>(`${BASE}/wechat/ilink/qrcode/status`, {
    params: { qr_id: qrId, ...(agentId ? { agent_id: agentId } : {}) },
  })
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
