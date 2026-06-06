/**
 * Logs API v2 Module
 * 日志 API v2 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface LogEntry {
  id: string
  level: 'debug' | 'info' | 'warning' | 'error' | 'critical'
  message: string
  source: string
  timestamp: number
  metadata?: Record<string, any>
}

export interface LogQuery {
  level?: string
  source?: string
  start?: number
  end?: number
  search?: string
  limit?: number
  offset?: number
}

export interface LogStats {
  total_logs: number
  logs_by_level: Record<string, number>
  logs_by_source: Record<string, number>
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 查询日志
 * @param query 查询参数
 * @returns 日志列表
 */
export async function queryLogs(query: LogQuery = {}): Promise<LogEntry[]> {
  return request({ url: `/api/v1/logs-api`, method: 'get', params: query })
}

/**
 * 获取日志详情
 * @param logId 日志ID
 * @returns 日志详情
 */
export async function getLogEntry(logId: string): Promise<LogEntry> {
  return request({ url: `/api/v1/logs-api/${logId}`, method: 'get' })
}

/**
 * 获取日志统计
 * @param period 时间范围
 * @returns 统计数据
 */
export async function getLogStats(period: string = 'day'): Promise<LogStats> {
  return request({ url: `/api/v1/logs-api/stats`, method: 'get', params: { period } })
}

/**
 * 获取日志源列表
 * @returns 日志源
 */
export async function getLogSources(): Promise<string[]> {
  return request({ url: `/api/v1/logs-api/sources`, method: 'get' })
}

/**
 * 清除旧日志
 * @param days 保留天数
 * @returns 清除结果
 */
export async function clearOldLogs(days: number = 30): Promise<ApiResponse<{ deleted: number }>> {
  return request({ url: `/api/v1/logs-api/clear`, method: 'delete', params: { days } })
}

/**
 * 导出日志
 * @param query 查询参数
 * @param format 导出格式 (json, csv)
 * @returns 日志数据
 */
export async function exportLogs(query: LogQuery = {}, format: string = 'json'): Promise<any> {
  return request({ url: `/api/v1/logs-api/export`, method: 'get', params: { ...query, format } })
}

/**
 * 实时日志流
 * @param level 日志级别
 * @param source 日志源
 * @returns SSE 连接 URL
 */
export async function getLogStreamUrl(level?: string, source?: string): Promise<ApiResponse<{ url: string }>> {
  return request({ url: `/api/v1/logs-api/stream`, method: 'get', params: { level, source } })
}

/**
 * 获取错误日志
 * @param limit 数量限制
 * @returns 错误日志列表
 */
export async function getErrorLogs(limit: number = 50): Promise<LogEntry[]> {
  return request({ url: `/api/v1/logs-api/errors`, method: 'get', params: { limit } })
}

/**
 * 搜索日志
 * @param query 搜索关键词
 * @param limit 数量限制
 * @returns 搜索结果
 */
export async function searchLogs(query: string, limit: number = 100): Promise<LogEntry[]> {
  return request({ url: `/api/v1/logs-api/search`, method: 'get', params: { q: query, limit } })
}