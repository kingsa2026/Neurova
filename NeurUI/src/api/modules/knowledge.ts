import api from '@/api'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface KnowledgeNode {
  id: string
  agent_id?: string
  title: string
  content: string
  category?: string
  tags?: string[]
  source?: string
  embedding?: number[]
  metadata?: Record<string, unknown>
  created_at: string
  updated_at?: string
}

export interface KnowledgeCreatePayload {
  agent_id?: string
  title: string
  content: string
  category?: string
  tags?: string[]
  source?: string
  metadata?: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/knowledge'

/** List knowledge nodes, optionally filtered by agent. */
export function getKnowledgeNodes(params?: PageParams & { agent_id?: string; category?: string; search?: string }) {
  return api.get<ApiResponse<PaginatedData<KnowledgeNode>>>(BASE, { params })
}

/** Get a single knowledge node. */
export function getKnowledgeNode(id: string) {
  return api.get<ApiResponse<KnowledgeNode>>(`${BASE}/${id}`)
}

/** Create a knowledge node. */
export function createKnowledgeNode(data: KnowledgeCreatePayload) {
  return api.post<ApiResponse<KnowledgeNode>>(BASE, data)
}

/** Update a knowledge node. */
export function updateKnowledgeNode(id: string, data: Partial<KnowledgeCreatePayload>) {
  return api.put<ApiResponse<KnowledgeNode>>(`${BASE}/${id}`, data)
}

/** Delete a knowledge node. */
export function deleteKnowledgeNode(id: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/${id}`)
}

/** Search knowledge nodes with semantic similarity. */
export function searchKnowledge(query: string, params?: { agent_id?: string; limit?: number; category?: string }) {
  return api.post<ApiResponse<KnowledgeNode[]>>(`${BASE}/search`, { query, ...params })
}
