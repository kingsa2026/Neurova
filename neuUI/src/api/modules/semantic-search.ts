/**
 * Semantic Search API Module
 * 语义搜索 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface SearchResult {
  id: string
  content: string
  score: number
  source: string
  metadata: Record<string, any>
}

export interface SearchRequest {
  query: string
  limit?: number
  threshold?: number
  filters?: Record<string, any>
}

export interface SearchStats {
  total_documents: number
  total_queries: number
  avg_response_time: number
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 语义搜索
 * @param data 搜索请求
 * @returns 搜索结果
 */
export async function semanticSearch(data: SearchRequest): Promise<SearchResult[]> {
  return request({ url: `/api/v1/semantic-search`, method: 'post', data })
}

/**
 * 获取搜索统计
 * @returns 统计数据
 */
export async function getSearchStats(): Promise<SearchStats> {
  return request({ url: `/api/v1/semantic-search/stats`, method: 'get' })
}

/**
 * 获取搜索历史
 * @param limit 数量限制
 * @returns 搜索历史
 */
export async function getSearchHistory(limit: number = 20): Promise<Array<{ query: string; timestamp: number; results_count: number }>> {
  return request({ url: `/api/v1/semantic-search/history`, method: 'get', params: { limit } })
}

/**
 * 索引文档
 * @param documentId 文档ID
 * @returns 索引结果
 */
export async function indexDocument(documentId: string): Promise<ApiResponse<{ id: string; indexed: boolean }>> {
  return request({ url: `/api/v1/semantic-search/index/${documentId}`, method: 'post' })
}

/**
 * 批量索引文档
 * @param documentIds 文档ID列表
 * @returns 索引结果
 */
export async function batchIndexDocuments(documentIds: string[]): Promise<ApiResponse<{ indexed: number; failed: number }>> {
  return request({ url: `/api/v1/semantic-search/index/batch`, method: 'post', data: { document_ids: documentIds } })
}

/**
 * 删除索引
 * @param documentId 文档ID
 * @returns 删除结果
 */
export async function deleteIndex(documentId: string): Promise<ApiResponse<{ id: string; deleted: boolean }>> {
  return request({ url: `/api/v1/semantic-search/index/${documentId}`, method: 'delete' })
}

/**
 * 获取索引状态
 * @returns 索引状态
 */
export async function getIndexStatus(): Promise<ApiResponse<{
  total_indexed: number
  pending_index: number
  failed_index: number
}>> {
  return request({ url: `/api/v1/semantic-search/index/status`, method: 'get' })
}