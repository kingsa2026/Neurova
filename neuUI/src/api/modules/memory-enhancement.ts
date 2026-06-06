/**
 * Memory Enhancement API Module
 * 记忆增强 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface MemoryEnhancement {
  id: string
  memory_id: string
  type: string
  content: string
  confidence: number
  source: string
  created_at: number
}

export interface EnhancementRequest {
  memory_id: string
  type: string
  params?: Record<string, any>
}

export interface EnhancementStats {
  total_enhancements: number
  by_type: Record<string, number>
  avg_confidence: number
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取记忆增强列表
 * @param memoryId 记忆ID
 * @returns 增强列表
 */
export async function getMemoryEnhancements(memoryId?: string): Promise<MemoryEnhancement[]> {
  return request({ url: `/api/v1/memory-enhancement`, method: 'get', params: { memory_id: memoryId } })
}

/**
 * 创建记忆增强
 * @param data 增强请求
 * @returns 创建的增强
 */
export async function createMemoryEnhancement(data: EnhancementRequest): Promise<MemoryEnhancement> {
  return request({ url: `/api/v1/memory-enhancement`, method: 'post', data })
}

/**
 * 删除记忆增强
 * @param enhancementId 增强ID
 * @returns 删除结果
 */
export async function deleteMemoryEnhancement(enhancementId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/memory-enhancement/${enhancementId}`, method: 'delete' })
}

/**
 * 获取增强统计
 * @returns 统计数据
 */
export async function getEnhancementStats(): Promise<EnhancementStats> {
  return request({ url: `/api/v1/memory-enhancement/stats`, method: 'get' })
}

/**
 * 获取支持的增强类型
 * @returns 增强类型列表
 */
export async function getEnhancementTypes(): Promise<string[]> {
  return request({ url: `/api/v1/memory-enhancement/types`, method: 'get' })
}

/**
 * 批量增强记忆
 * @param memoryIds 记忆ID列表
 * @param type 增强类型
 * @returns 批量增强结果
 */
export async function batchEnhanceMemories(
  memoryIds: string[],
  type: string
): Promise<ApiResponse<{ enhanced: number; failed: number }>> {
  return request({ url: `/api/v1/memory-enhancement/batch`, method: 'post', data: { memory_ids: memoryIds, type } })
}

/**
 * 获取增强质量报告
 * @param period 时间范围
 * @returns 质量报告
 */
export async function getEnhancementQualityReport(period: string = 'week'): Promise<ApiResponse<{
  total_enhancements: number
  avg_confidence: number
  success_rate: number
  by_type: Record<string, { count: number; avg_confidence: number }>
}>> {
  return request({ url: `/api/v1/memory-enhancement/quality`, method: 'get', params: { period } })
}