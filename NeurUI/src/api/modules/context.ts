import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface BuildContextRequest {
  agent_id?: string
  user_input: string
  session_id?: string
  max_tokens?: number
  include_reflection?: boolean
  include_memories?: boolean
  include_constitution?: boolean
  metadata?: Record<string, unknown>
}

export interface BuildContextResponse {
  context_id: string
  content: string
  token_count: number
  sources: string[]
  build_time: number
}

export interface ContextStats {
  total_contexts: number
  average_tokens: number
  cache_hit_rate: number
  compression_rate: number
}

export interface TokenBudget {
  max_tokens: number
  used_tokens: number
  available_tokens: number
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/context'

/** Build context for an agent. */
export function buildContext(data: BuildContextRequest) {
  return api.post<ApiResponse<BuildContextResponse>>(`${BASE}/build`, data)
}

/** Build context V2 (enhanced). */
export function buildContextV2(data: BuildContextRequest) {
  return api.post<ApiResponse<BuildContextResponse>>(`${BASE}/build/v2`, data)
}

/** Get context statistics. */
export function getContextStats() {
  return api.get<ApiResponse<ContextStats>>(`${BASE}/stats`)
}

/** Get context preview. */
export function getContextPreview(contextId: string) {
  return api.get<ApiResponse<{ context_id: string; content: string; token_count: number; sources: string[] }>>(`${BASE}/${contextId}/preview`)
}

/** Compress context. */
export function compressContext(contextId: string, targetTokens = 4000) {
  return api.post<ApiResponse<{ context_id: string; target_tokens: number }>>(`${BASE}/${contextId}/compress`, null, { params: { target_tokens: targetTokens } })
}

/** Inject reflection logs into context. */
export function injectReflection(agentId: string, limit = 10) {
  return api.get<ApiResponse<{ reflection_logs: unknown[]; count: number }>>(`${BASE}/inject/reflection`, { params: { agent_id: agentId, limit } })
}

/** Inject memories into context. */
export function injectMemories(agentId: string, query = '', limit = 10) {
  return api.get<ApiResponse<{ memories: unknown[]; count: number }>>(`${BASE}/inject/memories`, { params: { agent_id: agentId, query, limit } })
}

/** Inject hot memories into context. */
export function injectHotMemories(agentId: string, limit = 5) {
  return api.get<ApiResponse<{ hot_memories: unknown[]; count: number }>>(`${BASE}/inject/hot`, { params: { agent_id: agentId, limit } })
}

/** Get token budget. */
export function getTokenBudget(agentId: string) {
  return api.get<ApiResponse<TokenBudget>>(`${BASE}/token-budget`, { params: { agent_id: agentId } })
}

/** Set token budget. */
export function setTokenBudget(agentId: string, maxTokens: number) {
  return api.put<ApiResponse<{ max_tokens: number }>>(`${BASE}/token-budget`, null, { params: { agent_id: agentId, max_tokens: maxTokens } })
}
