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
