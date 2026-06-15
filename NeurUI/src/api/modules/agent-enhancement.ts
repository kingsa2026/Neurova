import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AgentStatus {
  agent_id: string
  status: string
  uptime: number
  memory_usage: number
  message_count: number
  last_active?: number
  created_at: number
}

export interface AgentCapabilities {
  agent_id: string
  capabilities: string[]
  tools: string[]
  models: string[]
  channels: string[]
}

export interface AgentHealth {
  agent_id: string
  healthy: boolean
  checks: Record<string, boolean>
  last_check: number
}

export interface RestartResponse {
  agent_id: string
  success: boolean
  message: string
  restart_time: number
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/agent-enhancement'

/** Get agent runtime status. */
export function getAgentStatus(agentId: string) {
  return api.get<ApiResponse<AgentStatus>>(`${BASE}/${agentId}/status`)
}

/** Get agent capabilities. */
export function getAgentCapabilities(agentId: string) {
  return api.get<ApiResponse<AgentCapabilities>>(`${BASE}/${agentId}/capabilities`)
}

/** Check agent health. */
export function getAgentHealth(agentId: string) {
  return api.get<ApiResponse<AgentHealth>>(`${BASE}/${agentId}/health`)
}

/** Restart an agent. */
export function restartAgent(agentId: string) {
  return api.post<ApiResponse<RestartResponse>>(`${BASE}/${agentId}/restart`)
}
