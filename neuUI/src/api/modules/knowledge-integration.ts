/**
 * Knowledge Integration API Module
 * 知识集成 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface KnowledgeSource {
  id: string
  name: string
  type: 'document' | 'database' | 'api' | 'web'
  config: Record<string, any>
  enabled: boolean
  last_sync?: number
  sync_count: number
}

export interface IntegrationJob {
  id: string
  source_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  started_at: number
  completed_at?: number
  items_processed: number
  errors: string[]
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取知识源列表
 * @returns 知识源列表
 */
export async function getKnowledgeSources(): Promise<KnowledgeSource[]> {
  return request({ url: `/api/v1/knowledge-integration/sources`, method: 'get' })
}

/**
 * 获取知识源详情
 * @param sourceId 知识源ID
 * @returns 知识源详情
 */
export async function getKnowledgeSource(sourceId: string): Promise<KnowledgeSource> {
  return request({ url: `/api/v1/knowledge-integration/sources/${sourceId}`, method: 'get' })
}

/**
 * 创建知识源
 * @param data 知识源数据
 * @returns 创建的知识源
 */
export async function createKnowledgeSource(data: Omit<KnowledgeSource, 'id' | 'last_sync' | 'sync_count'>): Promise<KnowledgeSource> {
  return request({ url: `/api/v1/knowledge-integration/sources`, method: 'post', data })
}

/**
 * 更新知识源
 * @param sourceId 知识源ID
 * @param data 更新数据
 * @returns 更新后的知识源
 */
export async function updateKnowledgeSource(sourceId: string, data: Partial<KnowledgeSource>): Promise<KnowledgeSource> {
  return request({ url: `/api/v1/knowledge-integration/sources/${sourceId}`, method: 'put', data })
}

/**
 * 删除知识源
 * @param sourceId 知识源ID
 * @returns 删除结果
 */
export async function deleteKnowledgeSource(sourceId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/knowledge-integration/sources/${sourceId}`, method: 'delete' })
}

/**
 * 同步知识源
 * @param sourceId 知识源ID
 * @returns 同步任务
 */
export async function syncKnowledgeSource(sourceId: string): Promise<IntegrationJob> {
  return request({ url: `/api/v1/knowledge-integration/sources/${sourceId}/sync`, method: 'post' })
}

/**
 * 获取同步任务列表
 * @param sourceId 知识源ID
 * @param limit 数量限制
 * @returns 任务列表
 */
export async function getSyncJobs(sourceId: string, limit: number = 10): Promise<IntegrationJob[]> {
  return request({ url: `/api/v1/knowledge-integration/sources/${sourceId}/jobs`, method: 'get', params: { limit } })
}

/**
 * 获取集成统计
 * @returns 统计数据
 */
export async function getKnowledgeIntegrationStats(): Promise<ApiResponse<{
  total_sources: number
  enabled_sources: number
  total_syncs: number
  total_items: number
}>> {
  return request({ url: `/api/v1/knowledge-integration/stats`, method: 'get' })
}