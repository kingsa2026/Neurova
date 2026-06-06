/**
 * Tool Layers API Module
 * 工具层管理 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface ToolLayer {
  id: string
  name: string
  description: string
  type: 'orchestrator' | 'marketplace' | 'registry'
  tools: string[]
  config: Record<string, any>
  enabled: boolean
  priority: number
  created_at: number
  updated_at: number
}

export interface CreateToolLayerRequest {
  name: string
  description?: string
  type?: 'orchestrator' | 'marketplace' | 'registry'
  tools?: string[]
  config?: Record<string, any>
  priority?: number
}

export interface UpdateToolLayerRequest {
  name?: string
  description?: string
  tools?: string[]
  config?: Record<string, any>
  enabled?: boolean
  priority?: number
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取工具层列表
 * @param params 查询参数
 * @returns 工具层列表
 */
export async function getToolLayers(params?: {
  type?: string
  enabled?: boolean
  limit?: number
  offset?: number
}): Promise<ToolLayer[]> {
  return request({
    url: `/api/v1/tool-layers`,
    method: 'get',
    params
  })
}

/**
 * 获取工具层详情
 * @param layerId 工具层ID
 * @returns 工具层详情
 */
export async function getToolLayer(layerId: string): Promise<ToolLayer> {
  return request({
    url: `/api/v1/tool-layers/${layerId}`,
    method: 'get'
  })
}

/**
 * 创建工具层
 * @param data 工具层数据
 * @returns 创建的工具层
 */
export async function createToolLayer(data: CreateToolLayerRequest): Promise<ToolLayer> {
  return request({
    url: `/api/v1/tool-layers`,
    method: 'post',
    data
  })
}

/**
 * 更新工具层
 * @param layerId 工具层ID
 * @param data 更新数据
 * @returns 更新后的工具层
 */
export async function updateToolLayer(layerId: string, data: UpdateToolLayerRequest): Promise<ToolLayer> {
  return request({
    url: `/api/v1/tool-layers/${layerId}`,
    method: 'put',
    data
  })
}

/**
 * 删除工具层
 * @param layerId 工具层ID
 * @returns 删除结果
 */
export async function deleteToolLayer(layerId: string): Promise<ApiResponse<{ id: string }>> {
  return request({
    url: `/api/v1/tool-layers/${layerId}`,
    method: 'delete'
  })
}

/**
 * 启用/禁用工具层
 * @param layerId 工具层ID
 * @param enabled 是否启用
 * @returns 更新后的工具层
 */
export async function toggleToolLayer(layerId: string, enabled: boolean): Promise<ToolLayer> {
  return request({
    url: `/api/v1/tool-layers/${layerId}/toggle`,
    method: 'put',
    params: { enabled }
  })
}

/**
 * 添加工具到层
 * @param layerId 工具层ID
 * @param toolId 工具ID
 * @returns 更新后的工具层
 */
export async function addToolToLayer(layerId: string, toolId: string): Promise<ToolLayer> {
  return request({
    url: `/api/v1/tool-layers/${layerId}/tools`,
    method: 'post',
    params: { tool_id: toolId }
  })
}

/**
 * 从层中移除工具
 * @param layerId 工具层ID
 * @param toolId 工具ID
 * @returns 更新后的工具层
 */
export async function removeToolFromLayer(layerId: string, toolId: string): Promise<ToolLayer> {
  return request({
    url: `/api/v1/tool-layers/${layerId}/tools/${toolId}`,
    method: 'delete'
  })
}

/**
 * 获取工具层统计
 * @returns 统计数据
 */
export async function getToolLayerStats(): Promise<ApiResponse<{
  total: number
  enabled: number
  disabled: number
  total_tools: number
  by_type: Record<string, number>
}>> {
  return request({
    url: `/api/v1/tool-layers/stats`,
    method: 'get'
  })
}