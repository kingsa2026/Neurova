import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TraceItem {
  id: string
  name?: string
  status: string
  duration_ms: number
  steps_count: number
  started_at?: string
  timestamp?: string
}

export interface TraceStats {
  total?: number
  avg_duration_ms?: number
  success_rate?: number
  avg_steps?: number
}

export interface ToolCall {
  tool: string
  name?: string
  duration_ms: number
  success: boolean
}

export interface LlmCall {
  model: string
  tokens_in: number
  tokens_out: number
  duration_ms: number
}

export interface TraceDetail extends TraceItem {
  tool_calls?: ToolCall[]
  llm_calls?: LlmCall[]
  breakdown?: Record<string, number>
  events?: TraceEvent[]
}

export interface TraceEvent {
  type: string
  timestamp: string
  message?: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/trace'

/** List traces for a given agent. */
export function listTraces(agentId: string) {
  return api.get<ApiResponse<{ items?: TraceItem[]; traces?: TraceItem[] } | TraceItem[]>>(`${BASE}`, { params: { agent_id: agentId } })
}

/** Get aggregate trace statistics for an agent. */
export function getTraceStats(agentId: string) {
  return api.get<ApiResponse<TraceStats>>(`${BASE}/stats`, { params: { agent_id: agentId } })
}

/** Get detailed trace info including tool/LLM calls. */
export function getTraceDetail(id: string) {
  return api.get<ApiResponse<TraceDetail>>(`${BASE}/${id}`)
}

/** Export a trace as a JSON blob. */
export function exportTrace(id: string) {
  return api.get<Blob>(`${BASE}/${id}/export`, { responseType: 'blob' })
}
