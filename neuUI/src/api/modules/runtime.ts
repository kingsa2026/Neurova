/**
 * Runtime API Module
 * 运行时管理 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface Runtime {
  id: string
  name: string
  type: 'local' | 'docker' | 'cloud'
  status: 'running' | 'stopped' | 'error'
  config: Record<string, any>
  resources: RuntimeResources
  created_at: number
  last_active?: number
}

export interface RuntimeResources {
  cpu_usage: number
  memory_usage: number
  disk_usage: number
  network_in: number
  network_out: number
}

export interface CreateRuntimeRequest {
  name: string
  type?: 'local' | 'docker' | 'cloud'
  config?: Record<string, any>
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取运行时列表
 * @returns 运行时列表
 */
export async function getRuntimes(): Promise<Runtime[]> {
  return request({ url: `/api/v1/runtime`, method: 'get' })
}

/**
 * 获取运行时详情
 * @param runtimeId 运行时ID
 * @returns 运行时详情
 */
export async function getRuntime(runtimeId: string): Promise<Runtime> {
  return request({ url: `/api/v1/runtime/${runtimeId}`, method: 'get' })
}

/**
 * 创建运行时
 * @param data 运行时配置
 * @returns 创建的运行时
 */
export async function createRuntime(data: CreateRuntimeRequest): Promise<Runtime> {
  return request({ url: `/api/v1/runtime`, method: 'post', data })
}

/**
 * 启动运行时
 * @param runtimeId 运行时ID
 * @returns 启动结果
 */
export async function startRuntime(runtimeId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/runtime/${runtimeId}/start`, method: 'post' })
}

/**
 * 停止运行时
 * @param runtimeId 运行时ID
 * @returns 停止结果
 */
export async function stopRuntime(runtimeId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/runtime/${runtimeId}/stop`, method: 'post' })
}

/**
 * 删除运行时
 * @param runtimeId 运行时ID
 * @returns 删除结果
 */
export async function deleteRuntime(runtimeId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/runtime/${runtimeId}`, method: 'delete' })
}

/**
 * 获取运行时资源使用情况
 * @param runtimeId 运行时ID
 * @returns 资源使用情况
 */
export async function getRuntimeResources(runtimeId: string): Promise<RuntimeResources> {
  return request({ url: `/api/v1/runtime/${runtimeId}/resources`, method: 'get' })
}

/**
 * 在运行时中执行命令
 * @param runtimeId 运行时ID
 * @param command 命令
 * @returns 执行结果
 */
export async function executeInRuntime(
  runtimeId: string,
  command: string
): Promise<ApiResponse<{ output: string; exit_code: number }>> {
  return request({ url: `/api/v1/runtime/${runtimeId}/execute`, method: 'post', params: { command } })
}

/**
 * 获取运行时日志
 * @param runtimeId 运行时ID
 * @param limit 日志行数
 * @returns 日志内容
 */
export async function getRuntimeLogs(runtimeId: string, limit: number = 100): Promise<string[]> {
  return request({ url: `/api/v1/runtime/${runtimeId}/logs`, method: 'get', params: { limit } })
}