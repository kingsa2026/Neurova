/**
 * Plugins API Module
 * 插件管理 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface Plugin {
  id: string
  name: string
  description: string
  version: string
  author: string
  type: 'builtin' | 'custom' | 'marketplace'
  enabled: boolean
  config: Record<string, any>
  permissions: string[]
  installed_at: number
  updated_at?: number
}

export interface InstallPluginRequest {
  name: string
  source: string
  version?: string
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取插件列表
 * @param params 查询参数
 * @returns 插件列表
 */
export async function getPlugins(params?: {
  type?: string
  enabled?: boolean
}): Promise<Plugin[]> {
  return request({ url: `/api/v1/plugins`, method: 'get', params })
}

/**
 * 获取插件详情
 * @param pluginId 插件ID
 * @returns 插件详情
 */
export async function getPlugin(pluginId: string): Promise<Plugin> {
  return request({ url: `/api/v1/plugins/${pluginId}`, method: 'get' })
}

/**
 * 安装插件
 * @param data 安装参数
 * @returns 安装的插件
 */
export async function installPlugin(data: InstallPluginRequest): Promise<Plugin> {
  return request({ url: `/api/v1/plugins/install`, method: 'post', data })
}

/**
 * 卸载插件
 * @param pluginId 插件ID
 * @returns 卸载结果
 */
export async function uninstallPlugin(pluginId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/plugins/${pluginId}`, method: 'delete' })
}

/**
 * 启用/禁用插件
 * @param pluginId 插件ID
 * @param enabled 是否启用
 * @returns 更新后的插件
 */
export async function togglePlugin(pluginId: string, enabled: boolean): Promise<Plugin> {
  return request({ url: `/api/v1/plugins/${pluginId}/toggle`, method: 'put', params: { enabled } })
}

/**
 * 更新插件配置
 * @param pluginId 插件ID
 * @param config 配置数据
 * @returns 更新后的插件
 */
export async function updatePluginConfig(pluginId: string, config: Record<string, any>): Promise<Plugin> {
  return request({ url: `/api/v1/plugins/${pluginId}/config`, method: 'put', data: config })
}

/**
 * 获取插件市场列表
 * @param query 搜索关键词
 * @returns 市场插件列表
 */
export async function searchMarketplace(query?: string): Promise<Plugin[]> {
  return request({ url: `/api/v1/plugins/marketplace`, method: 'get', params: { q: query } })
}

/**
 * 获取插件统计
 * @returns 统计数据
 */
export async function getPluginStats(): Promise<ApiResponse<{
  total: number
  enabled: number
  disabled: number
  by_type: Record<string, number>
}>> {
  return request({ url: `/api/v1/plugins/stats`, method: 'get' })
}