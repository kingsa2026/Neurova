import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface GeneralSettings {
  app_name: string
  language: string
}

export interface SecuritySettings {
  jwt_secret: string
  jwt_expiry_hours: number
  min_password_length: number
  require_special: boolean
}

export interface StorageSettings {
  media_path: string
  max_upload_mb: number
  cache_ttl_minutes: number
}

export interface AdvancedSettings {
  debug_mode: boolean
  log_level: string
  telemetry: boolean
  /** 全局默认输出预算（单次回复 max_tokens 上限）；131072 = 跟随模型默认 */
  max_output_tokens: number
  /** 桌面运行权限档：full/sandbox/review/auto */
  desktop_runtime_mode: string
}

export interface AppSettings {
  general: GeneralSettings
  security: SecuritySettings
  storage: StorageSettings
  advanced: AdvancedSettings
  providers?: string[]
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/settings'

/** Get all application settings. */
export function getSettings() {
  return api.get<ApiResponse<AppSettings>>(BASE)
}

/** Update a settings section. */
export function updateSettings(section: string, data: Record<string, unknown>) {
  return api.put<ApiResponse<null>>(BASE, { settings: { [section]: data } })
}

/** Clear application cache. */
export function clearCache() {
  return api.post<ApiResponse<null>>(`${BASE}/clear-cache`)
}

// ---------------------------------------------------------------------------
// SSH 多主机凭据（computer_ssh_exec 消费；按 host 分键，密钥/密码加密落盘不回显）
// ---------------------------------------------------------------------------

export interface SshHost {
  host: string
  user: string
  port: number
  /** 认证类型：key（私钥）/password/agent（系统默认） */
  auth: string
}

export interface SshCredentialPayload {
  host: string
  user?: string
  port?: number
  key_text?: string
  password?: string
}

export function listSSHCredentials() {
  return api.get<ApiResponse<{ hosts: SshHost[] }>>(`${BASE}/ssh-credentials`)
}

export function upsertSSHCredential(data: SshCredentialPayload) {
  return api.post<ApiResponse<{ host: string }>>(`${BASE}/ssh-credentials`, data)
}

export function deleteSSHCredential(host: string) {
  return api.delete<ApiResponse<{ host: string }>>(`${BASE}/ssh-credentials/${encodeURIComponent(host)}`)
}

// ---------------------------------------------------------------------------
// 社交平台凭据（web_reach social_exec 消费；与 SSH 复用同一配置面/加密桶）
// ---------------------------------------------------------------------------

export interface SocialPlatformStatus {
  platform: string
  keys: { key: string; set: boolean }[]
  configured: boolean
}

export function listSocialCredentials() {
  return api.get<ApiResponse<{ platforms: SocialPlatformStatus[] }>>(`${BASE}/social-credentials`)
}

export function setSocialCredential(platform: string, credentials: Record<string, string>) {
  return api.post<ApiResponse<{ platform: string }>>(`${BASE}/social-credentials`, { platform, credentials })
}

export function clearSocialCredential(platform: string) {
  return api.delete<ApiResponse<{ platform: string }>>(`${BASE}/social-credentials/${encodeURIComponent(platform)}`)
}

// ---------------------------------------------------------------------------
// Governance settings（进化治理：RSI 部署阶段 + 对话规则提取 LLM 成本门控）
// ---------------------------------------------------------------------------

export interface GovernanceSettings {
  conversation_rules_enabled: boolean
  rsi_phase: number
}

export function getGovernanceSettings() {
  return api.get<ApiResponse<GovernanceSettings>>('/governance/settings')
}

export function updateGovernanceSettings(data: Partial<GovernanceSettings>) {
  return api.put<ApiResponse<GovernanceSettings>>('/governance/settings', data)
}

// ---------------------------------------------------------------------------
// Agent 运行限制（Token 预算上限 / 单次会话最大 Loop 轮次）
// ---------------------------------------------------------------------------

export interface AgentLimits {
  token_budget: number
  max_loop_rounds: number
}

export function getAgentLimits() {
  return api.get<ApiResponse<AgentLimits>>('/governance/agent-limits')
}

export function updateAgentLimits(data: Partial<AgentLimits>) {
  return api.put<ApiResponse<AgentLimits>>('/governance/agent-limits', data)
}

// ---------------------------------------------------------------------------
// LLM 429 重试设置（设置页"模型"tab，ZCode 对齐 2026-09-11）
// ---------------------------------------------------------------------------

export interface LlmRetrySettings {
  /** 同模型最大等待重试次数 */
  max_retries: number
  /** 重试间隔秒（服务端 Retry-After 优先于该间隔） */
  interval: number
  /** 单次等待封顶秒 */
  wait_cap: number
  /** 连续失败模型容错数（任一模型成功出内容即归零重计） */
  max_switches: number
}

export function getLlmRetrySettings() {
  return api.get<ApiResponse<LlmRetrySettings>>('/governance/llm-retry')
}

export function updateLlmRetrySettings(data: Partial<LlmRetrySettings>) {
  return api.put<ApiResponse<LlmRetrySettings>>('/governance/llm-retry', data)
}
