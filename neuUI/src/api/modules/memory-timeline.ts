/**
 * Memory Timeline API Module
 * 记忆时间线 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface TimelineEvent {
  id: string
  type: string
  content: string
  timestamp: number
  importance: number
  tags: string[]
  related_events: string[]
}

export interface TimelineStats {
  total_events: number
  events_by_type: Record<string, number>
  avg_importance: number
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取时间线事件
 * @param params 查询参数
 * @returns 事件列表
 */
export async function getTimelineEvents(params?: {
  start?: number
  end?: number
  type?: string
  limit?: number
  offset?: number
}): Promise<TimelineEvent[]> {
  return request({ url: `/api/v1/memory-timeline`, method: 'get', params })
}

/**
 * 获取事件详情
 * @param eventId 事件ID
 * @returns 事件详情
 */
export async function getTimelineEvent(eventId: string): Promise<TimelineEvent> {
  return request({ url: `/api/v1/memory-timeline/${eventId}`, method: 'get' })
}

/**
 * 获取时间线统计
 * @returns 统计数据
 */
export async function getTimelineStats(): Promise<TimelineStats> {
  return request({ url: `/api/v1/memory-timeline/stats`, method: 'get' })
}

/**
 * 获取事件类型列表
 * @returns 事件类型
 */
export async function getEventTypes(): Promise<string[]> {
  return request({ url: `/api/v1/memory-timeline/types`, method: 'get' })
}

/**
 * 搜索时间线事件
 * @param query 搜索关键词
 * @param limit 数量限制
 * @returns 搜索结果
 */
export async function searchTimelineEvents(query: string, limit: number = 20): Promise<TimelineEvent[]> {
  return request({ url: `/api/v1/memory-timeline/search`, method: 'get', params: { q: query, limit } })
}

/**
 * 获取相关事件
 * @param eventId 事件ID
 * @param limit 数量限制
 * @returns 相关事件列表
 */
export async function getRelatedEvents(eventId: string, limit: number = 5): Promise<TimelineEvent[]> {
  return request({ url: `/api/v1/memory-timeline/${eventId}/related`, method: 'get', params: { limit } })
}

/**
 * 获取时间线聚合数据
 * @param granularity 聚合粒度 (hour, day, week)
 * @param start 开始时间
 * @param end 结束时间
 * @returns 聚合数据
 */
export async function getTimelineAggregation(
  granularity: string = 'day',
  start?: number,
  end?: number
): Promise<Array<{ timestamp: number; count: number; avg_importance: number }>> {
  return request({ url: `/api/v1/memory-timeline/aggregation`, method: 'get', params: { granularity, start, end } })
}