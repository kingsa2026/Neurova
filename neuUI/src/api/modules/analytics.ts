/**
 * Analytics API Module
 * 分析统计 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface AnalyticsOverview {
  total_users: number
  active_users: number
  total_agents: number
  active_agents: number
  total_conversations: number
  total_messages: number
  period: string
}

export interface UserAnalytics {
  user_id: string
  total_conversations: number
  total_messages: number
  avg_session_duration: number
  last_active: number
  preferred_features: string[]
}

export interface AgentAnalytics {
  agent_id: string
  total_conversations: number
  total_messages: number
  avg_response_time: number
  success_rate: number
  most_used_tools: string[]
}

export interface FeatureUsage {
  feature: string
  usage_count: number
  unique_users: number
  trend: 'up' | 'down' | 'stable'
}

export interface TimeSeriesData {
  timestamp: number
  value: number
  label?: string
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取概览统计
 * @param period 时间范围 (day, week, month, year)
 * @returns 概览数据
 */
export async function getAnalyticsOverview(period: string = 'month'): Promise<AnalyticsOverview> {
  return request({
    url: `/api/v1/analytics/overview`,
    method: 'get',
    params: { period }
  })
}

/**
 * 获取用户分析数据
 * @param params 查询参数
 * @returns 用户分析列表
 */
export async function getUserAnalytics(params?: {
  user_id?: string
  limit?: number
  offset?: number
}): Promise<UserAnalytics[]> {
  return request({
    url: `/api/v1/analytics/users`,
    method: 'get',
    params
  })
}

/**
 * 获取 Agent 分析数据
 * @param params 查询参数
 * @returns Agent 分析列表
 */
export async function getAgentAnalytics(params?: {
  agent_id?: string
  limit?: number
  offset?: number
}): Promise<AgentAnalytics[]> {
  return request({
    url: `/api/v1/analytics/agents`,
    method: 'get',
    params
  })
}

/**
 * 获取功能使用统计
 * @param limit 数量限制
 * @returns 功能使用列表
 */
export async function getFeatureUsage(limit: number = 20): Promise<FeatureUsage[]> {
  return request({
    url: `/api/v1/analytics/features`,
    method: 'get',
    params: { limit }
  })
}

/**
 * 获取时间序列数据
 * @param metric 指标名称 (users, messages, conversations)
 * @param period 时间范围
 * @param granularity 粒度 (hour, day, week)
 * @returns 时间序列数据
 */
export async function getTimeSeriesData(
  metric: string,
  period: string = 'month',
  granularity: string = 'day'
): Promise<TimeSeriesData[]> {
  return request({
    url: `/api/v1/analytics/timeseries`,
    method: 'get',
    params: { metric, period, granularity }
  })
}

/**
 * 获取实时统计
 * @returns 实时数据
 */
export async function getRealtimeStats(): Promise<ApiResponse<{
  online_users: number
  active_agents: number
  messages_per_minute: number
  avg_response_time: number
}>> {
  return request({
    url: `/api/v1/analytics/realtime`,
    method: 'get'
  })
}

/**
 * 导出分析报告
 * @param format 导出格式 (json, csv, pdf)
 * @param period 时间范围
 * @returns 报告数据
 */
export async function exportAnalyticsReport(
  format: string = 'json',
  period: string = 'month'
): Promise<any> {
  return request({
    url: `/api/v1/analytics/export`,
    method: 'get',
    params: { format, period }
  })
}