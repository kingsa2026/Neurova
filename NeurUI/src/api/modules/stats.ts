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
