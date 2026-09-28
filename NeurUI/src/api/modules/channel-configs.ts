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

// ---------------------------------------------------------------------------
// 通用二维码授权
// 覆盖 feishu/dingtalk/qq/wecom/wechat——扫码即取凭据回填表单后再保存。
// 后端返回裸对象（与 iLink 端点一致，无信封）。
// ---------------------------------------------------------------------------

/** GET 二维码结果：base64 PNG + 轮询 token。 */
export interface ChannelQrcode {
  qrcode_img: string
  poll_token: string
}

/** 轮询扫码状态：credentials 供成功后回填表单。 */
export interface ChannelQrcodeStatus {
  status: string
  credentials: Record<string, string>
}

/** 生成指定渠道的登录/授权二维码。params 透传（如 feishu 的 domain）。 */
export function getChannelQrcode(channel: string, params?: Record<string, string>) {
  return api.get<ChannelQrcode>(`${BASE}/${channel}/qrcode`, { params: params || {} })
}

/** 单次轮询扫码授权状态（未确认由调用方继续轮询）。 */
export function getChannelQrcodeStatus(channel: string, token: string, params?: Record<string, string>) {
  return api.get<ChannelQrcodeStatus>(`${BASE}/${channel}/qrcode/status`, {
    params: { token, ...(params || {}) },
  })
}

/** P0-5：入站持久化队列状态（裸对象，无信封）。 */
export function getIngressStats() {
  return api.get<ChannelIngressStats>(`${BASE}/ingress/stats`)
}

// ---------------------------------------------------------------------------
// B4-a 渠道管理能力面（restart / clear-queue / conflict-check）
// ---------------------------------------------------------------------------

/**
 * 重启渠道适配器（disconnect → connect，配置变更生效/断线重连）。
 *
 * agent 身份必须随行：实例表主键是 `(agent_id, type)`，同一平台在两个 agent
 * 下可以是两个独立 bot。不带参数时后端按 default 处置 —— 用户在「凯蒂」视图
 * 点重启，动的却是 default 的长连接，而屏幕上看不出差别。
 */
export function restartChannelAdapter(type: string, agentId?: string) {
  return api.post<{ code: number; message: string; data: { success: boolean; error?: string } }>(
    `/channel-adapters/${type}/restart`, undefined, { params: agentId ? { agent_id: agentId } : {} },
  )
}

/** 清空该 (agent, 渠道) 的待处理入站队列（积压清理）。 */
export function clearChannelQueue(type: string, agentId?: string) {
  return api.post<{ code: number; message: string; data: { cleared: number } }>(
    `/channel-adapters/${type}/clear-queue`, undefined, { params: agentId ? { agent_id: agentId } : {} },
  )
}

/** 机器人身份冲突检测（多渠道复用同一凭据）。 */
export function checkChannelConflicts() {
  return api.get<{ code: number; message: string; data: { conflicts: { identity: string; channels: string[] }[]; checked: number } }>(
    `/channel-adapters/conflicts/check`,
  )
}

/**
 * 存量渠道归属迁移：把源 agent（多为 `default`）名下已配置的渠道**移动**到目标 agent。
 *
 * 不传 `channelTypes` 即整表搬迁。后端是移动语义（源表清空），冲突时 409 并
 * **两边原样**返回——所以这里不吞错误，由调用方把原因显示给用户。
 */
export function migrateAgentChannelConfigs(
  fromAgentId: string,
  toAgentId: string,
  channelTypes?: string[],
) {
  return api.post<ApiResponse<{ success: boolean; from_agent_id: string; to_agent_id: string; migrated: string[] }>>(
    `${BASE}/migrate-agent`,
    {
      from_agent_id: fromAgentId,
      to_agent_id: toAgentId,
      ...(channelTypes && channelTypes.length ? { channel_types: channelTypes } : {}),
    },
  )
}

/** 插件渠道动态表单 schema（B4-d；未注册插件时为空数组）。 */
export function listPluginChannelSchemas() {
  return api.get<{ code: number; message: string; data: { schemas: { channel_type: string; name: string; config_fields: { key: string; label?: string; type: string; required?: boolean; default?: unknown; placeholder?: string }[] }[] } }>(
    `/channel-configs/schemas`,
  )
}
