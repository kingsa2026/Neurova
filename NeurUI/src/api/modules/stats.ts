import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SystemStats {
  overview?: Record<string, any>
  trends?: TrendPoint[]
  timeline?: TrendPoint[]
}

export interface TrendPoint {
  label: string
  value: number
}

export interface AgentStats {
  id: string
  name: string
  status?: string
  conversations?: number
  tokens?: number
  api_calls?: number
  errors?: number
}

export interface SystemInfo {
  status?: string
  cpu?: Record<string, unknown>
  memory?: { percent?: number; [k: string]: unknown }
  disk?: Record<string, unknown>
}

/** Per-model token usage entry (from usage accounting). */
export interface TokenUsageByModel {
  model: string
  calls: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

/** Process-level token usage snapshot (since server start). */
export interface TokenUsage {
  total: {
    calls: number
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
  }
  total_cost: number
  by_model: TokenUsageByModel[]
  last_call?: {
    model: string
    provider: string
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
  } | null
}

// ---------------------------------------------------------------------------
// 使用统计总览（持久化历史：data/usage_history.db）
// ---------------------------------------------------------------------------

export interface UsageOverviewHeatmapDay {
  date: string
  tokens: number
  calls: number
}

export interface UsageOverviewTrendPoint {
  date: string
  model: string
  tokens: number
}

export interface UsageOverviewModelTotal {
  model: string
  tokens: number
  calls: number
}

/** Kimi 式使用统计总览（/stats/usage-overview）。 */
export interface UsageOverview {
  scope?: 'user' | 'global'
  summary: {
    total_tokens: number
    total_calls: number
    peak_daily_tokens: number
    peak_daily_date: string | null
    longest_session_seconds: number
    current_streak_days: number
    longest_streak_days: number
    active_days: number
  }
  heatmap: UsageOverviewHeatmapDay[]
  trends: UsageOverviewTrendPoint[]
  by_model: UsageOverviewModelTotal[]
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/stats'

/** Get system-wide stats (overview + trends). */
export function getSystemStats() {
  return api.get<SystemStats>(BASE)
}

/** Get per-agent stats. */
export function getAgentStats() {
  return api.get<AgentStats[]>(`${BASE}/agents`)
}

/** Export stats as a downloadable blob. */
export function exportStats() {
  return api.get<Blob>(`${BASE}/export`, { responseType: 'blob' })
}

/** Get system health info (CPU, memory, disk). */
export function getSystemInfo() {
  return api.get<SystemInfo>(`${BASE}/system`)
}

/** Get process-level token usage (real accounting snapshot, since server start). */
export function getTokenUsage() {
  return api.get<TokenUsage>(`${BASE}/token-usage`)
}

/** Get persisted usage overview (SQLite history: summary + heatmap + per-model trend). */
export function getUsageOverview(params: { days?: number; trend_days?: number } = {}) {
  return api.get<UsageOverview>(`${BASE}/usage-overview`, { params })
}

/** P1-13 provider 真账单快照（默认关；usage_collection=true 的 provider 才有）。 */
export interface ProviderUsageSnapshot {
  provider_id: string
  ts: string
  plan?: string | null
  quota_remaining?: number | null
  currency?: string | null
  balance?: number | null
  window_days?: number | null
  raw?: Record<string, unknown>
}

export interface ProviderUsageResponse {
  snapshots: ProviderUsageSnapshot[]
  errors: { provider_id: string; error: string; ts: string }[]
}

/** Get provider billing snapshots (empty arrays when collector not installed). */
export function getProviderUsage() {
  return api.get<ProviderUsageResponse>(`${BASE}/provider-usage`)
}
