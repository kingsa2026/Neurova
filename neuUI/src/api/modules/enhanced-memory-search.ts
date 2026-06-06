/**
 * Enhanced Memory Search API Module
 * 增强记忆搜索 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface MemorySearchResult {
  id: string
  content: string
  type: string
  score: number
  source: string
  created_at: number
  metadata: Record<string, any>
}

export interface MemorySearchRequest {
  query: string
  memory_types?: string[]
  time_range?: { start: number; end: number }
  limit?: number
  threshold?: number
}

export interface MemorySearchStats {
  total_memories: number
  search_count: number
  avg_response_time: number
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 增强记忆搜索
 * @param data 搜索请求
 * @returns 搜索结果
 */
export async function enhancedMemorySearch(data: MemorySearchRequest): Promise<MemorySearchResult[]> {
  return request({ url: `/api/v1/enhanced-memory-search`, method: 'post', data })
}

/**
 * 获取记忆统计
 * @returns 统计数据
 */
export async function getMemorySearchStats(): Promise<MemorySearchStats> {
  return request({ url: `/api/v1/enhanced-memory-search/stats`, method: 'get' })
}

/**
 * 获取记忆类型列表
 * @returns 记忆类型
 */
export async function getMemoryTypes(): Promise<string[]> {
  return request({ url: `/api/v1/enhanced-memory-search/types`, method: 'get' })
}

/**
 * 获取相关记忆
 * @param memoryId 记忆ID
 * @param limit 数量限制
 * @returns 相关记忆列表
 */
export async function getRelatedMemories(memoryId: string, limit: number = 10): Promise<MemorySearchResult[]> {
  return request({ url: `/api/v1/enhanced-memory-search/related/${memoryId}`, method: 'get', params: { limit } })
}

/**
 * 获取记忆时间线
 * @param params 查询参数
 * @returns 时间线数据
 */
export async function getMemoryTimeline(params?: {
  start?: number
  end?: number
  type?: string
}): Promise<Array<{ timestamp: number; count: number; types: Record<string, number> }>> {
  return request({ url: `/api/v1/enhanced-memory-search/timeline`, method: 'get', params })
}

/**
 * 获取记忆聚类
 * @param limit 数量限制
 * @returns 聚类结果
 */
export async function getMemoryClusters(limit: number = 10): Promise<Array<{
  id: string
  label: string
  count: number
  centroid: number[]
}>> {
  return request({ url: `/api/v1/enhanced-memory-search/clusters`, method: 'get', params: { limit } })
}

/**
 * 获取记忆洞察
 * @returns 洞察数据
 */
export async function getMemoryInsights(): Promise<ApiResponse<{
  top_topics: Array<{ topic: string; count: number }>
  sentiment_distribution: Record<string, number>
  activity_patterns: Array<{ hour: number; count: number }>
}>> {
  return request({ url: `/api/v1/enhanced-memory-search/insights`, method: 'get' })
}