/**
 * Tools API Module
 * 工具管理 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface ToolSchema {
  id: string
  name: string
  description: string
  type: 'builtin' | 'custom' | 'skill'
  category: string
  parameters: ToolParameter[]
  returns: ToolReturn
  enabled: boolean
  usage_count: number
  last_used?: number
}

export interface ToolParameter {
  name: string
  type: string
  description: string
  required: boolean
  default?: any
  enum?: any[]
}

export interface ToolReturn {
  type: string
  description: string
}

export interface CreateToolRequest {
  name: string
  description: string
  type?: 'builtin' | 'custom' | 'skill'
  category?: string
  parameters: ToolParameter[]
  returns?: ToolReturn
}

export interface UpdateToolRequest {
  name?: string
  description?: string
  category?: string
  parameters?: ToolParameter[]
  returns?: ToolReturn
  enabled?: boolean
}

export interface ToolExecution {
  id: string
  tool_id: string
  input: Record<string, any>
  output: any
  status: 'success' | 'error' | 'timeout'
  duration_ms: number
  timestamp: number
  error?: string
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取工具列表
 * @param params 查询参数
 * @returns 工具列表
 */
export async function getTools(params?: {
  type?: string
  category?: string
  enabled?: boolean
  limit?: number
  offset?: number
}): Promise<ToolSchema[]> {
  return request({
    url: `/api/v1/tools`,
    method: 'get',
    params
  })
}

/**
 * 获取工具详情
 * @param toolId 工具ID
 * @returns 工具详情
 */
export async function getTool(toolId: string): Promise<ToolSchema> {
  return request({
    url: `/api/v1/tools/${toolId}`,
    method: 'get'
  })
}

/**
 * 创建工具
 * @param data 工具数据
 * @returns 创建的工具
 */
export async function createTool(data: CreateToolRequest): Promise<ToolSchema> {
  return request({
    url: `/api/v1/tools`,
    method: 'post',
    data
  })
}

/**
 * 更新工具
 * @param toolId 工具ID
 * @param data 更新数据
 * @returns 更新后的工具
 */
export async function updateTool(toolId: string, data: UpdateToolRequest): Promise<ToolSchema> {
  return request({
    url: `/api/v1/tools/${toolId}`,
    method: 'put',
    data
  })
}

/**
 * 删除工具
 * @param toolId 工具ID
 * @returns 删除结果
 */
export async function deleteTool(toolId: string): Promise<ApiResponse<{ id: string }>> {
  return request({
    url: `/api/v1/tools/${toolId}`,
    method: 'delete'
  })
}

/**
 * 启用/禁用工具
 * @param toolId 工具ID
 * @param enabled 是否启用
 * @returns 更新后的工具
 */
export async function toggleTool(toolId: string, enabled: boolean): Promise<ToolSchema> {
  return request({
    url: `/api/v1/tools/${toolId}/toggle`,
    method: 'put',
    params: { enabled }
  })
}

/**
 * 执行工具
 * @param toolId 工具ID
 * @param input 输入参数
 * @returns 执行结果
 */
export async function executeTool(
  toolId: string,
  input: Record<string, any>
): Promise<ToolExecution> {
  return request({
    url: `/api/v1/tools/${toolId}/execute`,
    method: 'post',
    data: input
  })
}

/**
 * 获取工具执行历史
 * @param toolId 工具ID
 * @param limit 数量限制
 * @returns 执行记录列表
 */
export async function getToolExecutions(toolId: string, limit: number = 20): Promise<ToolExecution[]> {
  return request({
    url: `/api/v1/tools/${toolId}/executions`,
    method: 'get',
    params: { limit }
  })
}

/**
 * 获取工具分类列表
 * @returns 分类列表
 */
export async function getToolCategories(): Promise<string[]> {
  return request({
    url: `/api/v1/tools/categories`,
    method: 'get'
  })
}

/**
 * 获取工具统计
 * @returns 统计数据
 */
export async function getToolStats(): Promise<ApiResponse<{
  total: number
  builtin: number
  custom: number
  skill: number
  enabled: number
  disabled: number
  total_executions: number
}>> {
  return request({
    url: `/api/v1/tools/stats`,
    method: 'get'
  })
}