import api from '@/api'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface KnowledgeNode {
  id: string
  knowledge_id?: string
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
  // 隔离与共享（批次 1）
  visibility?: 'public' | 'private'
  owner_user_id?: string
  shared_with?: string[]
  submission?: { status?: string; submitted_at?: string; reviewed_by?: string; note?: string } | null
  graph_node_ids?: string[]
  // P0-2 分块：块数 + 检索命中的块级溯源
  chunk_count?: number
  chunk_hits?: KnowledgeChunkHit[]
}

/** 检索命中的块级明细（chunk_index 定位 + 块正文 + 相关度得分） */
export interface KnowledgeChunkHit {
  chunk_index: number
  content: string
  score?: number
}

export type KnowledgeScope = 'all' | 'public' | 'private' | 'shared'

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
export function getKnowledgeNodes(params?: PageParams & { agent_id?: string; category?: string; search?: string; q?: string; scope?: KnowledgeScope }) {
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
export function updateKnowledgeNode(id: string, data: Partial<KnowledgeCreatePayload>, params?: { agent_id?: string }) {
  return api.put<ApiResponse<KnowledgeNode>>(`${BASE}/${id}`, data, { params })
}

/** Delete a knowledge node. */
export function deleteKnowledgeNode(id: string, params?: { agent_id?: string }) {
  return api.delete<ApiResponse<null>>(`${BASE}/${id}`, { params })
}

/** Search knowledge nodes with semantic similarity. */
export function searchKnowledge(query: string, params?: { agent_id?: string; limit?: number; category?: string; page?: number; page_size?: number; scope?: KnowledgeScope }) {
  return api.post<ApiResponse<KnowledgeNode[]>>(`${BASE}/search`, { query, ...params })
}

// ---------------------------------------------------------------------------
// Hybrid semantic search (batch 2: source=knowledge + confidence breakdown)
// ---------------------------------------------------------------------------

export interface ConfidenceBreakdown {
  bm25: number
  vector: number
  fts: number
  rrf: number
}

export interface HybridSearchResult {
  id: string
  title?: string
  content: string
  rrf_score: number
  score: number
  confidence_breakdown?: ConfidenceBreakdown
}

/** Hybrid (BM25+vector+FTS RRF) search over the current user's visible knowledge entries. */
export function hybridKnowledgeSearch(query: string, params?: { top_k?: number; scope?: KnowledgeScope }) {
  return api.post<ApiResponse<{ results: HybridSearchResult[]; total: number }>>(
    '/semantic-search/hybrid',
    { query, source: 'knowledge', ...params },
  )
}

// ---------------------------------------------------------------------------
// Sharing & public submission (batch 1 isolation)
// ---------------------------------------------------------------------------

/** Share a private node to given usernames (read-only for sharees). */
export function shareKnowledgeNode(id: string, usernames: string[]) {
  return api.post<ApiResponse<KnowledgeNode>>(`${BASE}/${id}/share`, { usernames })
}

/** Revoke sharing for given usernames. */
export function unshareKnowledgeNode(id: string, usernames: string[]) {
  return api.post<ApiResponse<KnowledgeNode>>(`${BASE}/${id}/unshare`, { usernames })
}

/** Submit a private node to the public KB (requires admin approval). */
export function submitKnowledgeToPublic(id: string) {
  return api.post<ApiResponse<KnowledgeNode>>(`${BASE}/${id}/submit-public`)
}

/** Admin: list pending public submissions. */
export function listPublicSubmissions() {
  return api.get<ApiResponse<KnowledgeNode[]>>(`${BASE}/public-submissions`)
}

/** Admin: approve or reject a public submission. */
export function reviewKnowledgePublic(id: string, approve: boolean, note = '') {
  return api.post<ApiResponse<KnowledgeNode>>(`${BASE}/${id}/review-public`, { approve, note })
}

// ---------------------------------------------------------------------------
// Remote KB configuration (R-7 A: user-level configs / collections)
// ---------------------------------------------------------------------------

export interface KbConfig {
  id: string
  name: string
  source_type: string
  is_default?: boolean
  is_active?: boolean
  settings?: Record<string, unknown>
  has_api_key?: boolean
  created_at?: string
  updated_at?: string
}

/** List current user's remote KB configs. */
export function listKbConfigs() {
  return api.get<ApiResponse<{ configs: KbConfig[] }>>(`${BASE}/configs`)
}

/** Create a remote KB config (api_key encrypted server-side). */
export function createKbConfig(data: {
  name: string
  source_type: string
  api_key?: string
  settings?: Record<string, unknown>
  is_default?: boolean
}) {
  return api.post<ApiResponse<{ id: string }>>(`${BASE}/configs`, data)
}

/** Update a remote KB config. */
export function updateKbConfig(id: string, data: Partial<{ name: string; source_type: string; api_key: string; settings: Record<string, unknown> }>) {
  return api.put<ApiResponse<null>>(`${BASE}/configs/${id}`, data)
}

/** Delete a remote KB config. */
export function deleteKbConfig(id: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/configs/${id}`)
}

export interface KbCollection {
  id: string
  config_id?: string
  collection_name?: string
  vector_store?: string
  created_at?: string
}

/** List current user's collection mappings. */
export function listKbCollections() {
  return api.get<ApiResponse<{ collections: KbCollection[] }>>(`${BASE}/collections`)
}

/** Create a collection mapping. */
export function createKbCollection(data: { config_id: string; collection_name: string; vector_store?: string }) {
  return api.post<ApiResponse<{ id: string }>>(`${BASE}/collections`, data)
}

/** Delete a collection mapping. */
export function deleteKbCollection(id: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/collections/${id}`)
}
