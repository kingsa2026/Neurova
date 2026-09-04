import api from '@/api'
import type { ApiResponse, PaginatedData } from '@/types/response'

// ---------------------------------------------------------------------------
// Core Types
// ---------------------------------------------------------------------------

export interface MemoryEntry {
  id: string
  agent_id: string
  content: string
  type: 'short_term' | 'long_term' | 'episodic' | 'semantic'
  category?: string
  importance: number
  temperature?: number
  is_important?: boolean
  is_crystallized?: boolean
  emotion_score?: number
  perspective?: string
  tags?: string[]
  metadata?: Record<string, unknown>
  created_at: string
  updated_at?: string
  expires_at?: string
}

export interface MemoryCreatePayload {
  content: string
  category?: string
  type?: string
  importance?: number
  is_important?: boolean
  is_crystallized?: boolean
  emotion_score?: number
  perspective?: string
  tags?: string[]
  metadata?: Record<string, unknown>
  auto_classify?: boolean
  classification_context?: string
  auto_analyze_emotion?: boolean
}

export interface MemorySearchResult {
  id: string
  content: string
  score: number
  type: string
  created_at: string
  channel_scores?: Record<string, number>
}

export interface MemoryStats {
  total_memories: number
  by_type: { type: string; count: number }[]
  avg_importance: number
  storage_used: number
}

// ---------------------------------------------------------------------------
// NeRF Types
// ---------------------------------------------------------------------------

export interface NerfSettings {
  fusion_mode: 'legacy' | 'nerf'
  density_scale: number
  channel_densities: Record<string, number>
  available_modes: string[]
  mode_descriptions: Record<string, string>
}

export interface NerfSettingsUpdate {
  fusion_mode?: 'legacy' | 'nerf'
  density_scale?: number
  channel_densities?: Record<string, number>
}

export interface ChannelWeights {
  intent: string
  weights: Record<string, number>
}

// ---------------------------------------------------------------------------
// Emotion Types
// ---------------------------------------------------------------------------

export interface EmotionSummary {
  total_annotated: number
  emotion_distribution: Record<string, number>
  emotion_weight?: number
}

export interface EmotionDistribution {
  [emotion: string]: number
}

export interface EmotionAnalysisResult {
  score: number
  tags: string[]
}

export interface EmotionTypeInfo {
  name: string
  weight: number
  description?: string
}

// ---------------------------------------------------------------------------
// EKI Cognitive Optimizer Types
// ---------------------------------------------------------------------------

export interface EKIStatus {
  enabled: boolean
  ensemble_size: number
  embed_dim: number
  use_surrogate: boolean
  auto_update: boolean
  last_update?: string
}

export interface EKIConfigPayload {
  ensemble_size?: number
  embed_dim?: number
  use_surrogate?: boolean
  auto_update?: boolean
}

export interface EKIStatistics {
  total_processed: number
  avg_confidence: number
  reinforcement_count: number
  decay_predictions: number
  last_activity?: string
}

export interface EKIDecayPrediction {
  memory_id: string
  current_strength: number
  predicted_strengths: Record<string, number>
  half_life_days: number
}

export interface EKIMemoryStrength {
  memory_id: string
  strength: number
  factors: Record<string, number>
}

export interface EKIReinforcement {
  memory_id: string
  content: string
  score: number
  recommendation: string
}

// ---------------------------------------------------------------------------
// Working Memory Types
// ---------------------------------------------------------------------------

export interface WorkingMemoryContext {
  turns: { role: string; content: string; metadata?: Record<string, unknown> }[]
  compressed_context?: string
  plan_cache_count: number
}

export interface WorkingMemoryStats {
  turn_count: number
  compressed: boolean
  plan_cache_size: number
  last_activity?: string
}

export interface ExecutionPlan {
  plan_id: string
  task_description: string
  steps: string[]
  task_type?: string
  success_rate?: number
}

// ---------------------------------------------------------------------------
// Self Model & User Profile Types
// ---------------------------------------------------------------------------

export interface SelfModel {
  narrative_identity: string
  values: string[]
  goals: string[]
  capabilities: string[]
  limitations: string[]
  preferred_style: string
}

export interface UserProfile {
  user_id: string
  preferences: Record<string, unknown>
  interaction_patterns: Record<string, unknown>
  conversation_style: string
  knowledge_level: string
}

// ---------------------------------------------------------------------------
// Emotion Analysis (under memory/memories/emotion)
// ---------------------------------------------------------------------------

export interface QuestionQueueStats {
  pending_count: number
  total_asked: number
  avg_per_day: number
}

export interface PendingQuestion {
  id: string
  question: string
  answer?: string
  created_at: string
}

// ---------------------------------------------------------------------------
// Temporal Knowledge Graph Types
// ---------------------------------------------------------------------------

export interface TemporalFact {
  entity: string
  attribute: string
  value: string
  timestamp: string
  confidence: number
  source?: string
  metadata?: Record<string, unknown>
}

export interface TKGStats {
  total_facts: number
  entities: number
  relations: number
  time_range: { earliest: string; latest: string }
}

export interface TKGPayload {
  entity: string
  attribute: string
  value: string
  timestamp?: string
  confidence?: number
  source?: string
  metadata?: Record<string, unknown>
}

export interface TKGQueryPayload {
  entity?: string
  relation?: string
  start_time?: string
  end_time?: string
  limit?: number
}

// ---------------------------------------------------------------------------
// Memory Enhancement Types
// ---------------------------------------------------------------------------

export interface MemoryCategory {
  category: string
  count: number
  avg_importance: number
}

export interface BatchOperationResult {
  processed: number
  succeeded: number
  failed: number
  errors: string[]
}

// ---------------------------------------------------------------------------
// Memory Share Group Types
// ---------------------------------------------------------------------------

export interface ShareGroup {
  group_id: string
  name: string
  description: string
  agent_ids: string[]
  created_at: string
  updated_at: string
  metadata?: Record<string, unknown>
}

export interface ShareGroupCreatePayload {
  name: string
  description: string
  agent_ids: string[]
  metadata?: Record<string, unknown>
}

export interface ShareGroupUpdatePayload {
  name?: string
  description?: string
  metadata?: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// Memory Timeline Types
// ---------------------------------------------------------------------------

export interface TimelineGroup {
  period: string
  count: number
  memories: MemoryEntry[]
}

export interface TimelineStats {
  total_periods: number
  most_active_period: string
  avg_per_period: number
}

// ---------------------------------------------------------------------------
// Enhanced Search & Semantic Search Types
// ---------------------------------------------------------------------------

export interface EnhancedSearchResult {
  id: string
  content: string
  score: number
  type: string
  channel_scores?: Record<string, number>
  metadata?: Record<string, unknown>
}

export interface SearchAnalysis {
  intent: string
  complexity: number
  suggested_method: string
  keywords: string[]
}

export interface MemoryActivation {
  memory_id: string
  activation: number
  factors: Record<string, number>
  last_accessed?: string
}

// ---------------------------------------------------------------------------
// Reflection Log Types
// ---------------------------------------------------------------------------

export interface ReflectionLog {
  id: string
  reflection_type: string
  situation: string
  thought: string
  action: string
  result: string
  lesson: string
  improvement?: string
  status: string
  validation_result?: string
  created_at: string
}

export interface ReflectionStats {
  total: number
  by_type: Record<string, number>
  by_status: Record<string, number>
  avg_lesson_quality?: number
}

// ===========================================================================
// API Functions
// ===========================================================================

// ---------------------------------------------------------------------------
// Core Memory CRUD  (prefix: /memory)
// ---------------------------------------------------------------------------

const BASE = '/memory'

/**
 * 解析记忆列表响应 data。
 * 后端列表端点（GET /memory、/hot、/crystallized）的信封统一为 {count, memories}，
 * 历史前端按 {items, total} 或数组解析会永远得到空列表。
 */
export function extractMemoryList(data: unknown): { items: MemoryEntry[]; total: number } {
  if (Array.isArray(data)) {
    return { items: data as MemoryEntry[], total: data.length }
  }
  if (data && typeof data === 'object') {
    const obj = data as Record<string, any>
    if (Array.isArray(obj.items)) {
      return { items: obj.items as MemoryEntry[], total: obj.total ?? obj.items.length }
    }
    if (Array.isArray(obj.memories)) {
      return { items: obj.memories as MemoryEntry[], total: obj.count ?? obj.memories.length }
    }
  }
  return { items: [], total: 0 }
}

/** List memories for an agent. 后端实参: query/category/limit（无分页 offset）。 */
export function getMemories(
  agentId: string,
  params?: { query?: string; category?: string; limit?: number; min_importance?: number },
) {
  return api.get<ApiResponse<{ count: number; memories: MemoryEntry[] }>>(BASE, {
    params: { ...params, agent_id: agentId },
  })
}

/** Get a single memory. */
export function getMemory(id: string) {
  return api.get<ApiResponse<MemoryEntry>>(`${BASE}/${id}`)
}

/** Create a memory. */
export function createMemory(data: MemoryCreatePayload, agentId?: string) {
  return api.post<ApiResponse<MemoryEntry>>(BASE, data, { params: agentId ? { agent_id: agentId } : undefined })
}

/** Update a memory. */
export function updateMemory(id: string, data: Partial<MemoryCreatePayload>) {
  return api.put<ApiResponse<MemoryEntry>>(`${BASE}/${id}`, data)
}

/** Delete a memory. */
export function deleteMemory(id: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/${id}`)
}

/** Search memories with semantic similarity. */
export function searchMemories(agentId: string, query: string, params?: { limit?: number; type?: string }) {
  return api.post<ApiResponse<MemorySearchResult[]>>(`${BASE}/search`, { agent_id: agentId, query, ...params })
}

/** Get memory statistics. */
export function getMemoryStats(agentId: string) {
  return api.get<ApiResponse<MemoryStats>>(`${BASE}/stats`, { params: { agent_id: agentId } })
}

/** Get high-temperature (hot) memories. */
export function getHotMemories(agentId: string, limit = 20) {
  return api.get<ApiResponse<MemoryEntry[]>>(`${BASE}/hot`, { params: { agent_id: agentId, limit } })
}

/** Get crystallized (permanent) memories. */
export function getCrystallizedMemories(agentId: string, limit = 20) {
  return api.get<ApiResponse<MemoryEntry[]>>(`${BASE}/crystallized`, { params: { agent_id: agentId, limit } })
}

/** Manually trigger temperature decay cycle. */
export function triggerDecay(agentId: string) {
  return api.post<ApiResponse<{ decayed: number }>>(`${BASE}/decay`, null, { params: { agent_id: agentId } })
}

// ---------------------------------------------------------------------------
// Markdown export/import  (prefix: /memory/markdown)  — P1 记忆可解释性
// ---------------------------------------------------------------------------

/** Markdown 导入结果统计。 */
export interface MemoryMarkdownImportStats {
  updated: number
  unchanged: number
  missing: number
  conflicts?: number
}

/** Export agent memories as readable markdown. */
export function exportMemoryMarkdown(agentId?: string, params?: { category?: string; limit?: number }) {
  return api.get<ApiResponse<{ markdown: string }>>(`${BASE}/markdown`, {
    params: { agent_id: agentId || undefined, ...params },
  })
}

/**
 * Submit (possibly edited) memory markdown. Only text-layer changes are
 * written back; embeddings / vector index stay untouched.
 */
export function importMemoryMarkdown(
  markdown: string,
  agentId?: string,
  strictVersion = false
) {
  return api.post<ApiResponse<{ stats: MemoryMarkdownImportStats }>>(
    `${BASE}/markdown`,
    { markdown, strict_version: strictVersion },
    { params: { agent_id: agentId || undefined } }
  )
}

// ---------------------------------------------------------------------------
// Emotion Analysis  (prefix: /memory/emotion)
// ---------------------------------------------------------------------------

const EMOTION_BASE = '/memory/emotion'

/** Query memories by emotion type. */
export function getMemoriesByEmotion(agentId: string, emotionType: string, params?: { min_score?: number; limit?: number }) {
  return api.get<ApiResponse<MemoryEntry[]>>(`${EMOTION_BASE}/${emotionType}`, { params: { ...params, agent_id: agentId } })
}

/** Get emotion statistics summary. */
export function getEmotionSummary(agentId: string) {
  return api.get<ApiResponse<EmotionSummary>>(`${EMOTION_BASE}/summary`, { params: { agent_id: agentId } })
}

/** Get emotion distribution. */
export function getEmotionDistribution(agentId: string) {
  return api.get<ApiResponse<EmotionDistribution>>(`${EMOTION_BASE}/distribution`, { params: { agent_id: agentId } })
}

/** Analyze text emotion. */
export function analyzeEmotion(agentId: string, text: string) {
  return api.post<ApiResponse<EmotionAnalysisResult>>(`${EMOTION_BASE}/analyze`, { text }, { params: { agent_id: agentId } })
}

/** Get supported emotion types and weights. */
export function getEmotionTypes() {
  return api.get<ApiResponse<EmotionTypeInfo[]>>(`${EMOTION_BASE}/types`)
}

// ---------------------------------------------------------------------------
// EKI Cognitive Optimizer  (prefix: /memory/eki)
// ---------------------------------------------------------------------------

const EKI_BASE = '/memory/eki'

/** Get EKI optimizer status. */
export function getEKIStatus(agentId: string) {
  return api.get<ApiResponse<EKIStatus>>(`${EKI_BASE}/status`, { params: { agent_id: agentId } })
}

/** Process EKI task. */
export function processEKITask(agentId: string, data: { task_embedding: number[]; memory_context: string[]; user_feedback?: number }) {
  return api.post<ApiResponse<Record<string, unknown>>>(`${EKI_BASE}/process`, data, { params: { agent_id: agentId } })
}

/** Get reinforcement recommendations. */
export function getEKIReinforcement(agentId: string, topK = 10) {
  return api.get<ApiResponse<EKIReinforcement[]>>(`${EKI_BASE}/reinforce`, { params: { agent_id: agentId, top_k: topK } })
}

/** Predict memory decay over time. */
export function predictEKIDecay(agentId: string, memoryId: string, horizon = 7) {
  return api.get<ApiResponse<EKIDecayPrediction>>(`${EKI_BASE}/decay/${memoryId}`, { params: { agent_id: agentId, horizon } })
}

/** Get memory strength. */
export function getEKIStrength(agentId: string, memoryId: string) {
  return api.get<ApiResponse<EKIMemoryStrength>>(`${EKI_BASE}/strength/${memoryId}`, { params: { agent_id: agentId } })
}

/** Get EKI statistics. */
export function getEKIStatistics(agentId: string) {
  return api.get<ApiResponse<EKIStatistics>>(`${EKI_BASE}/statistics`, { params: { agent_id: agentId } })
}

/** Batch update cognitive state. */
export function batchUpdateEKI(agentId: string, batchData: { memory_id: string; observations: unknown; obs_type: string }[]) {
  return api.post<ApiResponse<{ updated: number }>>(`${EKI_BASE}/batch-update`, { batch_data: batchData }, { params: { agent_id: agentId } })
}

/** Configure EKI optimizer parameters. */
export function configureEKI(agentId: string, config: EKIConfigPayload) {
  return api.put<ApiResponse<EKIStatus>>(`${EKI_BASE}/config`, config, { params: { agent_id: agentId } })
}

/** Enable or disable EKI optimizer. */
export function toggleEKI(agentId: string, enabled: boolean) {
  return api.put<ApiResponse<EKIStatus>>(`${EKI_BASE}/enable`, null, { params: { agent_id: agentId, enabled } })
}

// ---------------------------------------------------------------------------
// Metacognition (under memory)  (prefix: /memory/meta)
// ---------------------------------------------------------------------------

const META_BASE = '/memory/meta'

/** Run metacognition monitoring cycle. */
export function runMetaMonitor(agentId: string) {
  return api.post<ApiResponse<Record<string, unknown>>>(`${META_BASE}/monitor`, null, { params: { agent_id: agentId } })
}

/** Run metacognition reflection. */
export function runMetaReflect(agentId: string) {
  return api.post<ApiResponse<Record<string, unknown>>>(`${META_BASE}/reflect`, null, { params: { agent_id: agentId } })
}

/** Run metacognition optimization. */
export function runMetaOptimize(agentId: string) {
  return api.post<ApiResponse<Record<string, unknown>>>(`${META_BASE}/optimize`, null, { params: { agent_id: agentId } })
}

/** Run skill evolution. */
export function runMetaEvolveSkills(agentId: string) {
  return api.post<ApiResponse<Record<string, unknown>>>(`${META_BASE}/evolve-skills`, null, { params: { agent_id: agentId } })
}

/** Get metacognition health report. */
export function getMetaHealth(agentId: string) {
  return api.get<ApiResponse<Record<string, unknown>>>(`${META_BASE}/health`, { params: { agent_id: agentId } })
}

/** Get metacognition reflection report. */
export function getMetaReflection(agentId: string) {
  return api.get<ApiResponse<Record<string, unknown>>>(`${META_BASE}/reflection`, { params: { agent_id: agentId } })
}

/** Check if monitoring is needed. */
export function shouldMetaMonitor(agentId: string) {
  return api.get<ApiResponse<{ should_monitor: boolean; reason?: string }>>(`${META_BASE}/should-monitor`, { params: { agent_id: agentId } })
}

/** Check if reflection is needed. */
export function shouldMetaReflect(agentId: string) {
  return api.get<ApiResponse<{ should_reflect: boolean; reason?: string }>>(`${META_BASE}/should-reflect`, { params: { agent_id: agentId } })
}

/** Check if optimization is needed. */
export function shouldMetaOptimize(agentId: string) {
  return api.get<ApiResponse<{ should_optimize: boolean; reason?: string }>>(`${META_BASE}/should-optimize`, { params: { agent_id: agentId } })
}

/** Check if skill evolution is needed. */
export function shouldMetaEvolve(agentId: string) {
  return api.get<ApiResponse<{ should_evolve: boolean; reason?: string }>>(`${META_BASE}/should-evolve`, { params: { agent_id: agentId } })
}

/** Get all metacognition skills. */
export function getMetaSkills(agentId: string, params?: { category?: string; status?: string }) {
  return api.get<ApiResponse<Record<string, unknown>[]>>(`${META_BASE}/skills`, { params: { ...params, agent_id: agentId } })
}

/** Get skill statistics. */
export function getMetaSkillStats(agentId: string) {
  return api.get<ApiResponse<Record<string, unknown>>>(`${META_BASE}/skills/stats`, { params: { agent_id: agentId } })
}

/** Auto-generate a skill. */
export function generateMetaSkill(agentId: string, description: string, category?: string) {
  return api.post<ApiResponse<Record<string, unknown>>>(`${META_BASE}/skills/generate`, { description, category }, { params: { agent_id: agentId } })
}

/** Match skills to query. */
export function matchMetaSkills(agentId: string, query: string, topK = 5) {
  return api.post<ApiResponse<Record<string, unknown>[]>>(`${META_BASE}/skills/match`, { query, top_k: topK }, { params: { agent_id: agentId } })
}

// ---------------------------------------------------------------------------
// Reflection Log  (prefix: /memory/reflection)
// ---------------------------------------------------------------------------

const REFLECTION_BASE = '/memory/reflection'

/** Get reflection logs. */
export function getReflectionLogs(agentId: string, params?: { reflection_type?: string; status?: string; limit?: number; offset?: number }) {
  return api.get<ApiResponse<ReflectionLog[]>>(`${REFLECTION_BASE}/logs`, { params: { ...params, agent_id: agentId } })
}

/** Generate a reflection log. */
export function generateReflection(agentId: string, data: {
  reflection_type: string; situation: string; thought: string; action: string
  result: string; lesson: string; improvement?: string
  trigger_event?: string; related_memories?: string[]; emotion_score?: number; tags?: string[]
}) {
  return api.post<ApiResponse<ReflectionLog>>(`${REFLECTION_BASE}/generate`, data, { params: { agent_id: agentId } })
}

/** Validate a reflection log. */
export function validateReflection(agentId: string, logId: string, validationResult: string, feedback?: string) {
  return api.put<ApiResponse<ReflectionLog>>(`${REFLECTION_BASE}/${logId}/validate`, { validation_result: validationResult, feedback }, { params: { agent_id: agentId } })
}

/** Get reflection statistics. */
export function getReflectionStats(agentId: string) {
  return api.get<ApiResponse<ReflectionStats>>(`${REFLECTION_BASE}/stats`, { params: { agent_id: agentId } })
}

// ---------------------------------------------------------------------------
// Self Model & User Profile  (prefix: /memory)
// ---------------------------------------------------------------------------

/** Get self model. */
export function getSelfModel(agentId: string) {
  return api.get<ApiResponse<SelfModel>>(`${BASE}/self-model`, { params: { agent_id: agentId } })
}

/** Update self model. */
export function updateSelfModel(agentId: string, data: Partial<SelfModel>) {
  return api.put<ApiResponse<SelfModel>>(`${BASE}/self-model`, data, { params: { agent_id: agentId } })
}

/** Get user profile. */
export function getUserProfile(userId: string, agentId: string) {
  return api.get<ApiResponse<UserProfile>>(`${BASE}/users/${userId}/profile`, { params: { agent_id: agentId } })
}

/** Update user profile. */
export function updateUserProfile(userId: string, agentId: string, data: Partial<UserProfile>) {
  return api.put<ApiResponse<UserProfile>>(`${BASE}/users/${userId}/profile`, data, { params: { agent_id: agentId } })
}

// ---------------------------------------------------------------------------
// Question Queue  (prefix: /memory/questions)
// ---------------------------------------------------------------------------

const QUESTIONS_BASE = '/memory/questions'

/** Get pending questions. */
export function getPendingQuestions(agentId: string, limit = 20) {
  return api.get<ApiResponse<PendingQuestion[]>>(`${QUESTIONS_BASE}/pending`, { params: { agent_id: agentId, limit } })
}

/** Mark a question as asked. */
export function askQuestion(agentId: string, question: string, answer?: string) {
  return api.post<ApiResponse<Record<string, unknown>>>(`${QUESTIONS_BASE}/ask`, { question, answer }, { params: { agent_id: agentId } })
}

/** Get question queue statistics. */
export function getQuestionStats(agentId: string) {
  return api.get<ApiResponse<QuestionQueueStats>>(`${QUESTIONS_BASE}/stats`, { params: { agent_id: agentId } })
}

// ---------------------------------------------------------------------------
// Temporal Knowledge Graph  (prefix: /memory/tkg)
// ---------------------------------------------------------------------------

const TKG_BASE = '/memory/tkg'

/** Add a temporal fact. */
export function addTemporalFact(agentId: string, data: TKGPayload) {
  return api.post<ApiResponse<TemporalFact>>(`${TKG_BASE}/facts`, data, { params: { agent_id: agentId } })
}

/** Query temporal facts. */
export function queryTemporalFacts(agentId: string, data: TKGQueryPayload) {
  return api.post<ApiResponse<TemporalFact[]>>(`${TKG_BASE}/query`, data, { params: { agent_id: agentId } })
}

/** Get fact evolution history for an entity/relation. */
export function getFactHistory(agentId: string, entity: string, relation: string) {
  return api.get<ApiResponse<TemporalFact[]>>(`${TKG_BASE}/history/${encodeURIComponent(entity)}/${encodeURIComponent(relation)}`, { params: { agent_id: agentId } })
}

/** Get TKG statistics. */
export function getTKGStats(agentId: string) {
  return api.get<ApiResponse<TKGStats>>(`${TKG_BASE}/stats`, { params: { agent_id: agentId } })
}

// ---------------------------------------------------------------------------
// Working Memory  (prefix: /memory/wm)
// ---------------------------------------------------------------------------

const WM_BASE = '/memory/wm'

/** Add a dialogue turn to working memory. */
export function addDialogueTurn(agentId: string, role: string, content: string, metadata?: Record<string, unknown>) {
  return api.post<ApiResponse<Record<string, unknown>>>(`${WM_BASE}/turns`, { role, content, metadata }, { params: { agent_id: agentId } })
}

/** Get working memory context. */
export function getWorkingMemoryContext(agentId: string, params?: { max_turns?: number; use_folded?: boolean }) {
  return api.get<ApiResponse<WorkingMemoryContext>>(`${WM_BASE}/context`, { params: { ...params, agent_id: agentId } })
}

/** Compress content into working memory. */
export function compressWorkingMemory(agentId: string, content: string) {
  return api.post<ApiResponse<{ compressed: string }>>(`${WM_BASE}/compress`, { content }, { params: { agent_id: agentId } })
}

/** Cache an execution plan. */
export function cacheExecutionPlan(agentId: string, data: { task_description: string; steps: string[]; task_type?: string; context?: string }) {
  return api.post<ApiResponse<ExecutionPlan>>(`${WM_BASE}/plans`, data, { params: { agent_id: agentId } })
}

/** Retrieve a cached execution plan. */
export function retrieveExecutionPlan(agentId: string, taskDescription: string, taskType?: string, topK = 3) {
  return api.post<ApiResponse<ExecutionPlan[]>>(`${WM_BASE}/plans/retrieve`, { task_description: taskDescription, task_type: taskType, top_k: topK }, { params: { agent_id: agentId } })
}

/** Record execution plan result. */
export function recordPlanResult(agentId: string, planId: string, success: boolean) {
  return api.post<ApiResponse<Record<string, unknown>>>(`${WM_BASE}/plans/result`, { plan_id: planId, success }, { params: { agent_id: agentId } })
}

/** Get working memory statistics. */
export function getWorkingMemoryStats(agentId: string) {
  return api.get<ApiResponse<WorkingMemoryStats>>(`${WM_BASE}/stats`, { params: { agent_id: agentId } })
}

/** Clear working memory. */
export function clearWorkingMemory(agentId: string) {
  return api.delete<ApiResponse<{ cleared: boolean }>>(`${WM_BASE}`, { params: { agent_id: agentId } })
}

// ---------------------------------------------------------------------------
// Memory Enhancement  (prefix: /memory-enhancement)
// ---------------------------------------------------------------------------

const ENHANCE_BASE = '/memory-enhancement'

/** Forget (reduce importance) a memory. */
export function forgetMemory(memoryId: string, reason?: string, importanceThreshold = 0.3) {
  return api.post<ApiResponse<Record<string, unknown>>>(`${ENHANCE_BASE}/${memoryId}/forget`, { reason: reason || '', importance_threshold: importanceThreshold })
}

/** Strengthen a memory. */
export function strengthenMemory(memoryId: string, importanceBoost = 0.2, reason?: string) {
  return api.post<ApiResponse<Record<string, unknown>>>(`${ENHANCE_BASE}/${memoryId}/strengthen`, { importance_boost: importanceBoost, reason: reason || '' })
}

/** Get memory categories. */
export function getMemoryCategories() {
  return api.get<ApiResponse<MemoryCategory[]>>(`${ENHANCE_BASE}/categories`)
}

/** Batch operation on memories (forget/strengthen/delete). */
export function batchMemoryOperation(memoryIds: string[], operation: 'forget' | 'strengthen' | 'delete', params?: Record<string, unknown>) {
  return api.post<ApiResponse<BatchOperationResult>>(`${ENHANCE_BASE}/batch`, { memory_ids: memoryIds, operation, params: params || {} })
}

/** Export memories. */
export function exportMemories(params?: { format?: 'json' | 'csv'; category?: string; min_importance?: number }) {
  return api.get<ApiResponse<unknown>>(`${ENHANCE_BASE}/export`, { params })
}

/** Import memories. */
export function importMemories(memories: Record<string, unknown>[], mergeMode: 'skip' | 'overwrite' | 'merge' = 'skip') {
  return api.post<ApiResponse<{ imported: number; skipped: number; errors: string[] }>>(`${ENHANCE_BASE}/import`, { memories, merge_mode: mergeMode })
}

// ---------------------------------------------------------------------------
// Memory Share Groups  (prefix: /memory-share-groups)
// ---------------------------------------------------------------------------

const SHARE_BASE = '/memory-share-groups'

/** List all share groups. */
export function getShareGroups() {
  return api.get<ApiResponse<ShareGroup[]>>(SHARE_BASE)
}

/** Create a share group. */
export function createShareGroup(data: ShareGroupCreatePayload) {
  return api.post<ApiResponse<ShareGroup>>(SHARE_BASE, data)
}

/** Get a share group. */
export function getShareGroup(groupId: string) {
  return api.get<ApiResponse<ShareGroup>>(`${SHARE_BASE}/${groupId}`)
}

/** Update a share group. */
export function updateShareGroup(groupId: string, data: ShareGroupUpdatePayload) {
  return api.put<ApiResponse<ShareGroup>>(`${SHARE_BASE}/${groupId}`, data)
}

/** Delete a share group. */
export function deleteShareGroup(groupId: string) {
  return api.delete<ApiResponse<null>>(`${SHARE_BASE}/${groupId}`)
}

/** Add an agent to a share group. */
export function addAgentToShareGroup(groupId: string, agentId: string) {
  return api.post<ApiResponse<Record<string, unknown>>>(`${SHARE_BASE}/${groupId}/agents`, { agent_id: agentId })
}

/** Remove an agent from a share group. */
export function removeAgentFromShareGroup(groupId: string, agentId: string) {
  return api.delete<ApiResponse<null>>(`${SHARE_BASE}/${groupId}/agents/${agentId}`)
}

/** Get agents in a share group. */
export function getShareGroupAgents(groupId: string) {
  return api.get<ApiResponse<string[]>>(`${SHARE_BASE}/${groupId}/agents`)
}

/** Get groups for an agent. */
export function getAgentShareGroups(agentId: string) {
  return api.get<ApiResponse<ShareGroup[]>>(`${SHARE_BASE}/agent/${agentId}`)
}

/** Get shared agents for an agent. */
export function getSharedAgents(agentId: string) {
  return api.get<ApiResponse<string[]>>(`${SHARE_BASE}/agent/${agentId}/shared-agents`)
}

/** Check if two agents share a group. */
export function checkAgentSharing(agentId1: string, agentId2: string) {
  return api.get<ApiResponse<{ shared: boolean; groups?: string[] }>>(`${SHARE_BASE}/check/${agentId1}/${agentId2}`)
}

// ---------------------------------------------------------------------------
// Memory Timeline  (prefix: /memory-timeline)
// ---------------------------------------------------------------------------

const TIMELINE_BASE = '/memory-timeline'

/** Get recent memories. */
export function getRecentMemories(days = 7, limit = 50) {
  return api.get<ApiResponse<MemoryEntry[]>>(`${TIMELINE_BASE}/recent`, { params: { days, limit } })
}

/** Get memories by time range. */
export function getMemoriesByRange(start: string, end: string, page = 1, size = 20) {
  return api.get<ApiResponse<PaginatedData<MemoryEntry>>>(`${TIMELINE_BASE}/range`, { params: { start, end, page, size } })
}

/** Get grouped timeline (day/week/month). */
export function getGroupedTimeline(groupBy: 'day' | 'week' | 'month' = 'day', days = 30) {
  return api.get<ApiResponse<TimelineGroup[]>>(`${TIMELINE_BASE}/grouped`, { params: { group_by: groupBy, days } })
}

/** Get timeline statistics. */
export function getTimelineStats() {
  return api.get<ApiResponse<TimelineStats>>(`${TIMELINE_BASE}/stats`)
}

// ---------------------------------------------------------------------------
// Enhanced Memory Search  (prefix: /enhanced-memory-search)
// ---------------------------------------------------------------------------

const ENHANCED_BASE = '/enhanced-memory-search'

/** Get NeRF volume rendering settings. */
export function getNerfSettings() {
  return api.get<ApiResponse<NerfSettings>>(`${ENHANCED_BASE}/nerf-settings`)
}

/** Update NeRF volume rendering settings. */
export function updateNerfSettings(data: NerfSettingsUpdate) {
  return api.put<ApiResponse<NerfSettings>>(`${ENHANCED_BASE}/nerf-settings`, data)
}

/** Reset NeRF settings to defaults. */
export function resetNerfSettings() {
  return api.post<ApiResponse<NerfSettings>>(`${ENHANCED_BASE}/nerf-settings/reset`)
}

/** Get channel weights for a specific intent. */
export function getChannelWeights(intent: string) {
  return api.get<ApiResponse<ChannelWeights>>(`${ENHANCED_BASE}/channel-weights`, { params: { intent } })
}

/** Enhanced multi-layer search. */
export function enhancedSearch(query: string, params?: { top_k?: number; min_score?: number; include_metadata?: boolean }) {
  return api.post<ApiResponse<EnhancedSearchResult[]>>(`${ENHANCED_BASE}/search`, { query, ...params })
}

/** Get retrieval system stats. */
export function getEnhancedSearchStats() {
  return api.get<ApiResponse<Record<string, unknown>>>(`${ENHANCED_BASE}/stats`)
}

/** Get enhanced search settings. */
export function getEnhancedSearchSettings() {
  return api.get<ApiResponse<Record<string, unknown>>>(`${ENHANCED_BASE}/settings`)
}

/** Update enhanced search settings (decay config). */
export function updateEnhancedSearchSettings(data: Record<string, unknown>) {
  return api.put<ApiResponse<Record<string, unknown>>>(`${ENHANCED_BASE}/settings`, data)
}

/** Trigger activation decay. */
export function triggerActivationDecay() {
  return api.post<ApiResponse<{ decayed: number }>>(`${ENHANCED_BASE}/decay`)
}

/** Analyze query intent. */
export function analyzeQuery(query: string) {
  return api.post<ApiResponse<SearchAnalysis>>(`${ENHANCED_BASE}/analyze`, { query })
}

/** Get memory activation state. */
export function getMemoryActivation(memoryId: string) {
  return api.get<ApiResponse<MemoryActivation>>(`${ENHANCED_BASE}/activation/${memoryId}`)
}

// ---------------------------------------------------------------------------
// Semantic Search  (prefix: /semantic-search)
// ---------------------------------------------------------------------------

const SEMANTIC_BASE = '/semantic-search'

/** Hybrid search (BM25 + Vector + FTS5). */
export function hybridSearch(query: string, params?: { top_k?: number; bm25_weight?: number; vector_weight?: number; fts_weight?: number; filters?: Record<string, unknown> }) {
  return api.post<ApiResponse<EnhancedSearchResult[]>>(`${SEMANTIC_BASE}/hybrid`, { query, ...params })
}

/** Pure BM25 search. */
export function bm25Search(query: string, topK = 10) {
  return api.post<ApiResponse<EnhancedSearchResult[]>>(`${SEMANTIC_BASE}/bm25`, { query, top_k: topK })
}

/** Pure vector search. */
export function vectorSearch(query: string, topK = 10) {
  return api.post<ApiResponse<EnhancedSearchResult[]>>(`${SEMANTIC_BASE}/vector`, { query, top_k: topK })
}

/** Compare three search methods. */
export function compareSearchMethods(query: string, topK = 10) {
  return api.post<ApiResponse<Record<string, EnhancedSearchResult[]>>>(`${SEMANTIC_BASE}/compare`, { query, top_k: topK })
}

/** Analyze query features. */
export function analyzeSearchQuery(query: string) {
  return api.post<ApiResponse<SearchAnalysis>>(`${SEMANTIC_BASE}/analyze`, { query })
}

// ---------------------------------------------------------------------------
// P1-2 记忆待确认队列（Utopia pending_facts 裁剪版：交互式写入先入待审）
// ---------------------------------------------------------------------------

/** 待确认记忆记录。 */
export interface PendingMemory {
  id: string
  content: string
  category: string
  memory_type: string
  source_sentence: string
  status: 'pending' | 'confirmed' | 'rejected'
  proposed_by: string
  created_at: number
  decided_by?: string
  decided_at?: number
  note?: string
}

/** 待确认记忆清单（本人提议；admin 全量）。 */
export function listPendingMemories() {
  return api.get<ApiResponse<{ items: PendingMemory[]; total: number }>>(`${BASE}/pending`)
}

/** 确认记忆入主库。 */
export function confirmPendingMemory(id: string) {
  return api.post<ApiResponse<{ memory_id: string }>>(`${BASE}/pending/${id}/confirm`, { note: '' })
}

/** 拒绝记忆提议（同内容不再重复提议）。 */
export function rejectPendingMemory(id: string, note = '') {
  return api.post<ApiResponse<{ pending_id: string }>>(`${BASE}/pending/${id}/reject`, { note })
}

/** Admin: 裁决历史。 */
export function listPendingMemoryDecisions(status: 'confirmed' | 'rejected' = 'confirmed') {
  return api.get<ApiResponse<{ items: PendingMemory[]; total: number }>>(`${BASE}/pending/decisions`, {
    params: { status },
  })
}
