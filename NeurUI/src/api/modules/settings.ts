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
