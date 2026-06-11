import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MetacognitionEntry {
  id: string
  agent_id: string
  type: 'self_assessment' | 'strategy' | 'monitoring' | 'planning'
  content: string
  context?: string
  confidence?: number
  metadata?: Record<string, unknown>
  created_at: string
}

export interface MetacognitionCreatePayload {
  agent_id: string
  type: string
  content: string
  context?: string
  confidence?: number
  metadata?: Record<string, unknown>
}

export interface MetacognitionStats {
  total_entries: number
  by_type: { type: string; count: number }[]
  avg_confidence: number
  recent_trend: { date: string; count: number }[]
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/metacognition'

/** List metacognition entries. */
export function getMetacognitionEntries(agentId: string, params?: { page?: number; size?: number; type?: string }) {
  return api.get<ApiResponse<{ items: MetacognitionEntry[]; total: number }>>(BASE, { params: { ...params, agent_id: agentId } })
}

/** Create a metacognition entry. */
export function createMetacognition(data: MetacognitionCreatePayload) {
  return api.post<ApiResponse<MetacognitionEntry>>(BASE, data)
}

/** Get metacognition statistics. */
export function getMetacognitionStats(agentId: string) {
  return api.get<ApiResponse<MetacognitionStats>>(`${BASE}/stats`, { params: { agent_id: agentId } })
}
