/**
 * Sandbox API Module
 * 沙箱管理 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface Sandbox {
  id: string
  name: string
  status: 'running' | 'stopped' | 'error'
  type: 'python' | 'node' | 'docker'
  config: Record<string, any>
  created_at: number
  last_active?: number
  timeout: number
}

export interface ExecuteRequest {
  code: string
  language?: string
  timeout?: number
}

export interface ExecuteResult {
  output: string
  error?: string
  exit_code: number
  execution_time: number
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取沙箱列表
 * @returns 沙箱列表
 */
export async function getSandboxList(): Promise<Sandbox[]> {
  return request({ url: `/api/v1/sandbox`, method: 'get' })
}

/**
 * 获取沙箱详情
 * @param sandboxId 沙箱ID
 * @returns 沙箱详情
 */
export async function getSandbox(sandboxId: string): Promise<Sandbox> {
  return request({ url: `/api/v1/sandbox/${sandboxId}`, method: 'get' })
}

/**
 * 创建沙箱
 * @param name 沙箱名称
 * @param type 沙箱类型
 * @returns 创建的沙箱
 */
export async function createSandbox(name: string, type: string = 'python'): Promise<Sandbox> {
  return request({ url: `/api/v1/sandbox`, method: 'post', params: { name, type } })
}

/**
 * 删除沙箱
 * @param sandboxId 沙箱ID
 * @returns 删除结果
 */
export async function deleteSandbox(sandboxId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/sandbox/${sandboxId}`, method: 'delete' })
}

/**
 * 在沙箱中执行代码
 * @param sandboxId 沙箱ID
 * @param data 执行请求
 * @returns 执行结果
 */
export async function executeInSandbox(sandboxId: string, data: ExecuteRequest): Promise<ExecuteResult> {
  return request({ url: `/api/v1/sandbox/${sandboxId}/execute`, method: 'post', data })
}

/**
 * 获取沙箱文件列表
 * @param sandboxId 沙箱ID
 * @param path 目录路径
 * @returns 文件列表
 */
export async function getSandboxFiles(sandboxId: string, path: string = '/'): Promise<string[]> {
  return request({ url: `/api/v1/sandbox/${sandboxId}/files`, method: 'get', params: { path } })
}

/**
 * 读取沙箱文件
 * @param sandboxId 沙箱ID
 * @param filePath 文件路径
 * @returns 文件内容
 */
export async function readSandboxFile(sandboxId: string, filePath: string): Promise<string> {
  return request({ url: `/api/v1/sandbox/${sandboxId}/files/read`, method: 'get', params: { path: filePath } })
}

/**
 * 写入沙箱文件
 * @param sandboxId 沙箱ID
 * @param filePath 文件路径
 * @param content 文件内容
 * @returns 写入结果
 */
export async function writeSandboxFile(
  sandboxId: string,
  filePath: string,
  content: string
): Promise<ApiResponse<{ path: string }>> {
  return request({ url: `/api/v1/sandbox/${sandboxId}/files/write`, method: 'post', params: { path: filePath, content } })
}

/**
 * 获取沙箱统计
 * @returns 统计数据
 */
export async function getSandboxStats(): Promise<ApiResponse<{
  total: number
  running: number
  stopped: number
  total_executions: number
}>> {
  return request({ url: `/api/v1/sandbox/stats`, method: 'get' })
}