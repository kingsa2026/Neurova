/**
 * Agent Enhancement API Module
 * Agent 增强 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface AgentEnhancement {
  id: string
  agent_id: string
  type: string
  config: Record<string, any>
  enabled: boolean
  performance: EnhancementPerformance
  created_at: number
  updated_at: number
}

export interface EnhancementPerformance {
  accuracy: number
  latency_ms: number
  success_rate: number
  usage_count: number
}

export interface CreateEnhancementRequest {
  agent_id: string
  type: string
  config?: Record<string, any>
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取增强列表
 * @param agentId Agent ID
 * @returns 增强列表
 */
export async function getAgentEnhancements(agentId?: string): Promise<AgentEnhancement[]> {
  return request({ url: `/api/v1/agent-enhancement`, method: 'get', params: { agent_id: agentId } })
}

/**
 * 获取增强详情
 * @param enhancementId 增强ID
 * @returns 增强详情
 */
export async function getAgentEnhancement(enhancementId: string): Promise<AgentEnhancement> {
  return request({ url: `/api/v1/agent-enhancement/${enhancementId}`, method: 'get' })
}

/**
 * 创建增强
 * @param data 增强数据
 * @returns 创建的增强
 */
export async function createAgentEnhancement(data: CreateEnhancementRequest): Promise<AgentEnhancement> {
  return request({ url: `/api/v1/agent-enhancement`, method: 'post', data })
}

/**
 * 更新增强
 * @param enhancementId 增强ID
 * @param data 更新数据
 * @returns 更新后的增强
 */
export async function updateAgentEnhancement(
  enhancementId: string,
  data: Partial<CreateEnhancementRequest>
): Promise<AgentEnhancement> {
  return request({ url: `/api/v1/agent-enhancement/${enhancementId}`, method: 'put', data })
}

/**
 * 删除增强
 * @param enhancementId 增强ID
 * @returns 删除结果
 */
export async function deleteAgentEnhancement(enhancementId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/agent-enhancement/${enhancementId}`, method: 'delete' })
}

/**
 * 启用/禁用增强
 * @param enhancementId 增强ID
 * @param enabled 是否启用
 * @returns 更新后的增强
 */
export async function toggleAgentEnhancement(enhancementId: string, enabled: boolean): Promise<AgentEnhancement> {
  return request({ url: `/api/v1/agent-enhancement/${enhancementId}/toggle`, method: 'put', params: { enabled } })
}

/**
 * 获取增强统计
 * @returns 统计数据
 */
export async function getAgentEnhancementStats(): Promise<ApiResponse<{
  total: number
  enabled: number
  disabled: number
  by_type: Record<string, number>
}>> {
  return request({ url: `/api/v1/agent-enhancement/stats`, method: 'get' })
}

/**
 * 获取增强性能报告
 * @param enhancementId 增强ID
 * @param period 时间范围
 * @returns 性能报告
 */
export async function getEnhancementPerformance(
  enhancementId: string,
  period: string = 'day'
): Promise<EnhancementPerformance> {
  return request({ url: `/api/v1/agent-enhancement/${enhancementId}/performance`, method: 'get', params: { period } })
}

/**
 * 获取支持的增强类型
 * @returns 增强类型列表
 */
export async function getSupportedEnhancementTypes(): Promise<string[]> {
  return request({ url: `/api/v1/agent-enhancement/types`, method: 'get' })
}