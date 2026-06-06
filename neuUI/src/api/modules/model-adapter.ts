/**
 * Model Adapter API Module
 * 模型适配器 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface ModelAdapter {
  id: string
  name: string
  description: string
  source_type: 'openai' | 'anthropic' | 'gemini' | 'ollama' | 'custom'
  target_type: string
  config: Record<string, any>
  enabled: boolean
  created_at: number
  updated_at: number
}

export interface CreateAdapterRequest {
  name: string
  description?: string
  source_type: string
  target_type: string
  config?: Record<string, any>
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取适配器列表
 * @returns 适配器列表
 */
export async function getModelAdapters(): Promise<ModelAdapter[]> {
  return request({ url: `/api/v1/model-adapter`, method: 'get' })
}

/**
 * 获取适配器详情
 * @param adapterId 适配器ID
 * @returns 适配器详情
 */
export async function getModelAdapter(adapterId: string): Promise<ModelAdapter> {
  return request({ url: `/api/v1/model-adapter/${adapterId}`, method: 'get' })
}

/**
 * 创建适配器
 * @param data 适配器数据
 * @returns 创建的适配器
 */
export async function createModelAdapter(data: CreateAdapterRequest): Promise<ModelAdapter> {
  return request({ url: `/api/v1/model-adapter`, method: 'post', data })
}

/**
 * 更新适配器
 * @param adapterId 适配器ID
 * @param data 更新数据
 * @returns 更新后的适配器
 */
export async function updateModelAdapter(
  adapterId: string,
  data: Partial<CreateAdapterRequest>
): Promise<ModelAdapter> {
  return request({ url: `/api/v1/model-adapter/${adapterId}`, method: 'put', data })
}

/**
 * 删除适配器
 * @param adapterId 适配器ID
 * @returns 删除结果
 */
export async function deleteModelAdapter(adapterId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/model-adapter/${adapterId}`, method: 'delete' })
}

/**
 * 启用/禁用适配器
 * @param adapterId 适配器ID
 * @param enabled 是否启用
 * @returns 更新后的适配器
 */
export async function toggleModelAdapter(adapterId: string, enabled: boolean): Promise<ModelAdapter> {
  return request({ url: `/api/v1/model-adapter/${adapterId}/toggle`, method: 'put', params: { enabled } })
}

/**
 * 测试适配器连接
 * @param adapterId 适配器ID
 * @returns 测试结果
 */
export async function testModelAdapter(adapterId: string): Promise<ApiResponse<{ success: boolean; message: string }>> {
  return request({ url: `/api/v1/model-adapter/${adapterId}/test`, method: 'post' })
}

/**
 * 获取支持的源类型
 * @returns 源类型列表
 */
export async function getSupportedSourceTypes(): Promise<string[]> {
  return request({ url: `/api/v1/model-adapter/source-types`, method: 'get' })
}

/**
 * 获取支持的目标类型
 * @returns 目标类型列表
 */
export async function getSupportedTargetTypes(): Promise<string[]> {
  return request({ url: `/api/v1/model-adapter/target-types`, method: 'get' })
}

/**
 * 获取适配器统计
 * @returns 统计数据
 */
export async function getModelAdapterStats(): Promise<ApiResponse<{
  total: number
  enabled: number
  disabled: number
  by_source: Record<string, number>
}>> {
  return request({ url: `/api/v1/model-adapter/stats`, method: 'get' })
}