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

/** List knowledge nodes, optionally filtered by agent.
 * 2026-09-06 契约对齐：后端分页认 page/page_size（limit/offset 兼容），
 * 响应为 {items,total,page,page_size} 信封（此前 page_size 被静默忽略 → 恒前 20 条）。 */
export function getKnowledgeNodes(params?: PageParams & { agent_id?: string; category?: string; search?: string; q?: string; scope?: KnowledgeScope; page_size?: number }) {
  const { size, ...rest } = params ?? {}
  const query = { ...rest, page_size: rest.page_size ?? size }
  return api.get<ApiResponse<PaginatedData<KnowledgeNode>>>(BASE, { params: query })
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

// ── P2 标注闭环：精准回复命中表 ──

export interface AnnotationItem {
  id: string
  question: string
  answer: string
  source: string
  enabled: boolean
  hit_count: number
  created_at: number
  updated_at: number
}

/** 标注清单（按命中次数排序；q 过滤问题/答案子串） */
export function listAnnotations(q = '', limit = 100) {
  return api.get<ApiResponse<{ items: AnnotationItem[]; total: number }>>(`${BASE}/annotations`, {
    params: { q, limit },
  })
}

/** 新增精准回复 */
export function createAnnotation(question: string, answer: string) {
  return api.post<ApiResponse<{ id: string }>>(`${BASE}/annotations`, { question, answer })
}

/** 更新答案/启停用 */
export function updateAnnotation(id: string, data: { answer?: string; enabled?: boolean }) {
  return api.put<ApiResponse<AnnotationItem>>(`${BASE}/annotations/${id}`, data)
}

/** 删除标注 */
export function deleteAnnotation(id: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/annotations/${id}`)
}

/** 重训练化集导出（JSONL） */
export function exportAnnotationTrainingSet() {
  return api.get<ApiResponse<{ jsonl: string; count: number }>>(`${BASE}/annotations/export`)
}

// ---------------------------------------------------------------------------
// P0-2 revision 账本 / tombstone + P0-3 同值冲突（Utopia 对标落地）
// ---------------------------------------------------------------------------

/** 知识条目 revision（update 前的旧值快照）。 */
export interface KnowledgeRevision {
  old: Record<string, unknown>
  changed_fields: string[]
  updated_at: string
}

/** 知识条目 revision 账本（最新在前）。 */
export function listKnowledgeRevisions(id: string) {
  return api.get<KnowledgeRevision[]>(`${BASE}/${id}/revisions`)
}

/** 墓碑记录（软删条目审计视图）。 */
export interface DeletedKnowledge {
  knowledge_id: string
  title: string
  owner_user_id: string
  deleted_at: number
  deleted_by: string
  superseded_by: string | null
}

/** Admin: 墓碑清单。 */
export function listDeletedKnowledge() {
  return api.get<DeletedKnowledge[]>(`${BASE}/deleted`)
}

/** 属主/管理员：从墓碑复活条目。 */
export function restoreKnowledgeNode(id: string) {
  return api.post<{ code: number; message: string }>(`${BASE}/${id}/restore`)
}

/** 同值冲突记录（新条目疑似"同一事实的新说法"）。 */
export interface KnowledgeConflict {
  conflict_id: string
  old_id: string
  new_id: string
  title: string
  similarity: number
  reason: string
  detected_at: number
  status: string
}

/** Admin: 同值冲突清单（pending 待审 / resolved 历史）。 */
export function listKnowledgeConflicts(status: 'pending' | 'resolved' = 'pending') {
  return api.get<KnowledgeConflict[]>(`${BASE}/conflicts`, { params: { status } })
}

/** Admin: 裁决冲突。keep_both=保留双条目；supersede_old=新说法接管（旧条目入墓碑）。 */
export function resolveKnowledgeConflict(conflictId: string, resolution: 'keep_both' | 'supersede_old') {
  return api.post<{ code: number; message: string }>(`${BASE}/conflicts/${conflictId}/resolve`, { resolution })
}

// ---------------------------------------------------------------------------
// P1-1 图谱实体消解（灰区对人工队列 + 攒批裁决）
// ---------------------------------------------------------------------------

/** 图谱消解灰区对（转人工的低置信对）。 */
export interface GraphResolutionReview {
  review_id: string
  left_id: string
  right_id: string
  left_label: string
  right_label: string
  similarity: number
  status: string
  created_at: number
}

/** Admin: 实体消解人工队列。 */
export function listResolutionReviews(agentId: string, status: 'pending' | 'resolved' = 'pending') {
  return api.get<ApiResponse<{ reviews: GraphResolutionReview[] }>>(
    `/knowledge-graph/${agentId}/knowledge-graph/resolution/reviews`,
    { params: { status } },
  )
}

/** Admin: 人工裁决灰区对。merged=执行合并（可回滚）；kept=不同实体。 */
export function resolveResolutionReview(agentId: string, reviewId: string, decision: 'merged' | 'kept') {
  return api.post<{ code: number; message: string }>(
    `/knowledge-graph/${agentId}/knowledge-graph/resolution/reviews/${reviewId}/resolve`,
    { decision },
  )
}

/** Admin: 跑一轮消解（灰区召回 + LLM 攒批裁决；未配 LLM 全部转人工）。 */
export function runEntityResolution(agentId: string) {
  return api.post<ApiResponse<{ result: { merged: number; kept: number; escalated: number }; human_reviews: number }>>(
    `/knowledge-graph/${agentId}/knowledge-graph/resolution/run`,
  )
}
