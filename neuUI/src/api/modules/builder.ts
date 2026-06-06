/**
 * Builder API Module
 * 构建器 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface Build {
  id: string
  name: string
  type: string
  status: 'pending' | 'running' | 'success' | 'failed'
  config: Record<string, any>
  logs: string[]
  started_at?: number
  completed_at?: number
  duration_ms?: number
}

export interface CreateBuildRequest {
  name: string
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
 * 获取构建列表
 * @returns 构建列表
 */
export async function getBuilds(): Promise<Build[]> {
  return request({ url: `/api/v1/builder`, method: 'get' })
}

/**
 * 获取构建详情
 * @param buildId 构建ID
 * @returns 构建详情
 */
export async function getBuild(buildId: string): Promise<Build> {
  return request({ url: `/api/v1/builder/${buildId}`, method: 'get' })
}

/**
 * 创建构建
 * @param data 构建配置
 * @returns 创建的构建
 */
export async function createBuild(data: CreateBuildRequest): Promise<Build> {
  return request({ url: `/api/v1/builder`, method: 'post', data })
}

/**
 * 启动构建
 * @param buildId 构建ID
 * @returns 启动结果
 */
export async function startBuild(buildId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/builder/${buildId}/start`, method: 'post' })
}

/**
 * 取消构建
 * @param buildId 构建ID
 * @returns 取消结果
 */
export async function cancelBuild(buildId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/builder/${buildId}/cancel`, method: 'post' })
}

/**
 * 获取构建日志
 * @param buildId 构建ID
 * @param limit 日志行数
 * @returns 日志内容
 */
export async function getBuildLogs(buildId: string, limit: number = 100): Promise<string[]> {
  return request({ url: `/api/v1/builder/${buildId}/logs`, method: 'get', params: { limit } })
}

/**
 * 删除构建
 * @param buildId 构建ID
 * @returns 删除结果
 */
export async function deleteBuild(buildId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/builder/${buildId}`, method: 'delete' })
}

/**
 * 获取构建模板
 * @returns 模板列表
 */
export async function getBuildTemplates(): Promise<Record<string, any>[]> {
  return request({ url: `/api/v1/builder/templates`, method: 'get' })
}

/**
 * 获取构建统计
 * @returns 统计数据
 */
export async function getBuildStats(): Promise<ApiResponse<{
  total: number
  success: number
  failed: number
  avg_duration: number
}>> {
  return request({ url: `/api/v1/builder/stats`, method: 'get' })
}