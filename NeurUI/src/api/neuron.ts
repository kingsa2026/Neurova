/**
 * NEURON 系统 API 客户端
 * 
 * 提供依赖图谱、级联推理、缺失推理等 API 调用接口。
 */

// 批 W2：改走统一 api 单例（带鉴权拦截器）——修前裸 axios 实例不带
// Authorization 头，NeuronPage 整页必 401 静默失效。
// NEURON 面挂在 `/api/neuron`（不在统一实例的 `/api/v1` 下）：逐调用覆写
// baseURL，既复用鉴权/刷新/解包拦截器，又不会把请求打到错前缀。
import type { AxiosRequestConfig } from 'axios'
import api from '@/api'

const NEURON_BASE: AxiosRequestConfig = { baseURL: '/api/neuron' }

// ============ 实体 API ============

export interface Entity {
  id: string
  name: string
  entity_type: string
  metadata: Record<string, any>
  created_at: number
  updated_at: number
}

export interface EntityCreate {
  name: string
  entity_type: string
  metadata?: Record<string, any>
}

export async function listEntities(
  entityType?: string,
  limit: number = 100
): Promise<{ success: boolean; data: Entity[]; total: number }> {
  const params: Record<string, any> = { limit }
  if (entityType) params.entity_type = entityType
  return api.get('/entities', { ...NEURON_BASE, params })
}

export async function createEntity(
  entity: EntityCreate
): Promise<{ success: boolean; data: Entity; message: string }> {
  return api.post('/entities', entity, NEURON_BASE)
}

// ============ 依赖 API ============

export interface Dependency {
  id: string
  source_id: string
  target_id: string
  dep_type: string
  confidence: number
  evidence: string[]
  metadata: Record<string, any>
  created_at: number
}

export interface DependencyCreate {
  source_id: string
  target_id: string
  dep_type: string
  confidence?: number
}

export async function createDependency(
  dep: DependencyCreate
): Promise<{ success: boolean; data: Dependency; message: string }> {
  return api.post('/dependencies', dep, NEURON_BASE)
}

export async function getEntityDependencies(
  entityId: string,
  direction: string = 'both',
  maxDepth: number = 5
): Promise<{ success: boolean; data: { entity_id: string; downstream: string[]; upstream: string[] } }> {
  return api.get(`/dependencies/${entityId}`, {
    ...NEURON_BASE,
    params: { direction, max_depth: maxDepth },
  })
}

// ============ 级联推理 API ============

export interface CascadeEffect {
  entity_id: string
  effect_type: string
  confidence: number
}

export interface CascadeResult {
  source_entity: string
  direction: string
  total_affected: number
  confidence: number
  effects: CascadeEffect[]
  reasoning_chain: string[]
}

export async function cascadeReasoning(
  entityId: string,
  direction: string = 'forward',
  maxDepth: number = 5
): Promise<{ success: boolean; data: CascadeResult }> {
  return api.post('/cascade', {
    entity_id: entityId,
    direction,
    max_depth: maxDepth,
  }, NEURON_BASE)
}

export async function wouldAffect(
  sourceId: string,
  targetId: string,
  threshold: number = 0.5
): Promise<{ success: boolean; data: { would_affect: boolean; confidence: number; paths: string[][] } }> {
  return api.post('/would-affect', null, {
    ...NEURON_BASE,
    params: { source_id: sourceId, target_id: targetId, threshold },
  })
}

// ============ 缺失推理 API ============

export interface AbsenceResult {
  is_absent: boolean
  entity_exists: boolean
  relation_exists: boolean
  context_has_dependency: boolean
  confidence: number
  explanation: string[]
  suggestions: string[]
}

export async function detectAbsence(
  expectedEntity: string,
  expectedRelation: string,
  contextEntities: string[] = []
): Promise<{ success: boolean; data: AbsenceResult }> {
  return api.post('/absence/detect', {
    expected_entity: expectedEntity,
    expected_relation: expectedRelation,
    context_entities: contextEntities,
  }, NEURON_BASE)
}

// ============ 依赖提取 API ============

export interface ExtractedDependency {
  source: Record<string, any>
  target: Record<string, any>
  dep_type: string
  confidence: number
  evidence: string
}

export async function extractDependencies(
  memoryId: string,
  content: string,
  metadata?: Record<string, any>
): Promise<{ success: boolean; data: ExtractedDependency[]; total: number }> {
  return api.post('/extract', {
    memory_id: memoryId,
    content,
    metadata: metadata || {},
  }, NEURON_BASE)
}

// ============ 统计 API ============

export interface NeuronStats {
  total_entities: number
  total_edges: number
  entity_types: number
  dependency_types: number
}

export async function getNeuronStats(): Promise<{ success: boolean; data: NeuronStats }> {
  return api.get('/stats', NEURON_BASE)
}

export async function neuronHealth(): Promise<{ success: boolean; status: string; components: Record<string, string> }> {
  return api.get('/health', NEURON_BASE)
}

export default api
