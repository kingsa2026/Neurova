import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SyncStatus {
  status: 'idle' | 'syncing' | 'error'
  last_sync?: string
  total_nodes: number
  synced_nodes: number
  errors: string[]
}

export interface RetrievalResult {
  id: string
  title: string
  content: string
  score: number
  source?: string
  metadata?: Record<string, unknown>
}

export interface GapAnalysis {
  total_nodes: number
  gaps: { category: string; missing_count: number; suggestions: string[] }[]
  coverage_score: number
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/knowledge-integration'

/** Trigger a sync of the knowledge base. */
export function syncKnowledge(agentId: string) {
  return api.post<ApiResponse<SyncStatus>>(`${BASE}/sync`, { agent_id: agentId })
}

/** Get current sync status. */
export function getSyncStatus(agentId: string) {
  return api.get<ApiResponse<SyncStatus>>(`${BASE}/sync/status`, { params: { agent_id: agentId } })
}

/** RAG retrieve: query the knowledge base for relevant context. */
export function retrieveContext(agentId: string, query: string, topK = 5) {
  return api.post<ApiResponse<RetrievalResult[]>>(`${BASE}/retrieve`, { agent_id: agentId, query, top_k: topK })
}

/** Analyze knowledge gaps for an agent. */
export function analyzeGaps(agentId: string) {
  return api.get<ApiResponse<GapAnalysis>>(`${BASE}/gaps`, { params: { agent_id: agentId } })
}

/** Trigger learning from a conversation or document. */
export function learnFromContent(agentId: string, content: string, source?: string) {
  return api.post<ApiResponse<{ learned_count: number }>>(`${BASE}/learn`, { agent_id: agentId, content, source })
}

/** Get integration statistics. */
export function getIntegrationStats(agentId: string) {
  return api.get<ApiResponse<{ total: number; categories: number; avg_score: number; last_updated: string }>>(`${BASE}/stats`, { params: { agent_id: agentId } })
}

/** Batch import knowledge from external sources. */
export function batchImport(agentId: string, items: { title: string; content: string; category?: string }[]) {
  return api.post<ApiResponse<{ imported: number }>>(`${BASE}/batch-import`, { agent_id: agentId, items })
}

/** Export knowledge base. */
export function exportKnowledge(agentId: string, format: 'json' | 'markdown' = 'json') {
  return api.get<ApiResponse<Blob>>(`${BASE}/export`, { params: { agent_id: agentId, format }, responseType: format === 'json' ? 'json' : 'blob' } as any)
}
