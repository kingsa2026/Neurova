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
  pools: number
  total_contexts: number
  average_resident: number
  archived_total: number
  ledger_rows: number
  indexed_entries: number
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
  return api.post<ApiResponse<{
    context_id: string
    target_tokens: number
    original_tokens: number
    compressed_tokens: number
    dropped_segments: number
    content: string
  }>>(`${BASE}/${contextId}/compress`, null, { params: { target_tokens: targetTokens } })
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

/** Context composition 快照（usage 环图兜底 + 面板数据源；404=尚无实测，降级 debug 不刷红）。 */
export function getContextComposition(params: { agent_id: string; session_id?: string }) {
  return api.get<ApiResponse<Record<string, unknown>>>(`${BASE}/composition`, {
    params,
    __expectedStatus: 404,
  })
}
