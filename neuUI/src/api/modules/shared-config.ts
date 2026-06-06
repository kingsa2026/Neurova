/**
 * Shared Config API Module
 * 共享配置 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface SharedConfig {
  id: string
  key: string
  value: any
  type: 'string' | 'number' | 'boolean' | 'json' | 'array'
  description: string
  scope: 'global' | 'agent' | 'user'
  created_at: number
  updated_at: number
}

export interface UpdateConfigRequest {
  value: any
  description?: string
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取配置列表
 * @param params 查询参数
 * @returns 配置列表
 */
export async function getSharedConfigs(params?: {
  scope?: string
  search?: string
}): Promise<SharedConfig[]> {
  return request({ url: `/api/v1/shared-config`, method: 'get', params })
}

/**
 * 获取配置详情
 * @param configId 配置ID
 * @returns 配置详情
 */
export async function getSharedConfig(configId: string): Promise<SharedConfig> {
  return request({ url: `/api/v1/shared-config/${configId}`, method: 'get' })
}

/**
 * 根据 key 获取配置值
 * @param key 配置键
 * @returns 配置值
 */
export async function getConfigByKey(key: string): Promise<ApiResponse<{ value: any }>> {
  return request({ url: `/api/v1/shared-config/key/${key}`, method: 'get' })
}

/**
 * 创建配置
 * @param data 配置数据
 * @returns 创建的配置
 */
export async function createSharedConfig(data: Omit<SharedConfig, 'id' | 'created_at' | 'updated_at'>): Promise<SharedConfig> {
  return request({ url: `/api/v1/shared-config`, method: 'post', data })
}

/**
 * 更新配置
 * @param configId 配置ID
 * @param data 更新数据
 * @returns 更新后的配置
 */
export async function updateSharedConfig(configId: string, data: UpdateConfigRequest): Promise<SharedConfig> {
  return request({ url: `/api/v1/shared-config/${configId}`, method: 'put', data })
}

/**
 * 删除配置
 * @param configId 配置ID
 * @returns 删除结果
 */
export async function deleteSharedConfig(configId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/shared-config/${configId}`, method: 'delete' })
}

/**
 * 批量更新配置
 * @param configs 配置列表
 * @returns 更新结果
 */
export async function batchUpdateConfigs(
  configs: Array<{ key: string; value: any }>
): Promise<ApiResponse<{ updated: number }>> {
  return request({ url: `/api/v1/shared-config/batch`, method: 'post', data: { configs } })
}

/**
 * 导出配置
 * @param scope 配置范围
 * @returns 配置数据
 */
export async function exportConfigs(scope?: string): Promise<Record<string, any>> {
  return request({ url: `/api/v1/shared-config/export`, method: 'get', params: { scope } })
}

/**
 * 导入配置
 * @param configs 配置数据
 * @returns 导入结果
 */
export async function importConfigs(configs: Record<string, any>): Promise<ApiResponse<{ imported: number }>> {
  return request({ url: `/api/v1/shared-config/import`, method: 'post', data: configs })
}

/**
 * 获取配置统计
 * @returns 统计数据
 */
export async function getSharedConfigStats(): Promise<ApiResponse<{
  total: number
  by_scope: Record<string, number>
  by_type: Record<string, number>
}>> {
  return request({ url: `/api/v1/shared-config/stats`, method: 'get' })
}