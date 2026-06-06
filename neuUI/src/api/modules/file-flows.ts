/**
 * File Flows API Module
 * 文件流管理 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface FileFlow {
  id: string
  name: string
  description: string
  source: FileFlowNode
  target: FileFlowNode
  transforms: FileTransform[]
  status: 'active' | 'paused' | 'error'
  created_at: number
  updated_at: number
  last_run?: number
  run_count: number
}

export interface FileFlowNode {
  type: 'file' | 'directory' | 's3' | 'ftp' | 'http'
  path: string
  config?: Record<string, any>
}

export interface FileTransform {
  type: 'filter' | 'transform' | 'validate' | 'compress' | 'encrypt'
  params: Record<string, any>
}

export interface CreateFileFlowRequest {
  name: string
  description?: string
  source: FileFlowNode
  target: FileFlowNode
  transforms?: FileTransform[]
}

export interface UpdateFileFlowRequest {
  name?: string
  description?: string
  source?: FileFlowNode
  target?: FileFlowNode
  transforms?: FileTransform[]
  status?: 'active' | 'paused'
}

export interface FileFlowRun {
  id: string
  flow_id: string
  status: 'running' | 'completed' | 'failed'
  started_at: number
  completed_at?: number
  files_processed: number
  errors: string[]
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取文件流列表
 * @param params 查询参数
 * @returns 文件流列表
 */
export async function getFileFlows(params?: {
  status?: string
  limit?: number
  offset?: number
}): Promise<FileFlow[]> {
  return request({
    url: `/api/v1/file-flows`,
    method: 'get',
    params
  })
}

/**
 * 获取文件流详情
 * @param flowId 文件流ID
 * @returns 文件流详情
 */
export async function getFileFlow(flowId: string): Promise<FileFlow> {
  return request({
    url: `/api/v1/file-flows/${flowId}`,
    method: 'get'
  })
}

/**
 * 创建文件流
 * @param data 文件流数据
 * @returns 创建的文件流
 */
export async function createFileFlow(data: CreateFileFlowRequest): Promise<FileFlow> {
  return request({
    url: `/api/v1/file-flows`,
    method: 'post',
    data
  })
}

/**
 * 更新文件流
 * @param flowId 文件流ID
 * @param data 更新数据
 * @returns 更新后的文件流
 */
export async function updateFileFlow(flowId: string, data: UpdateFileFlowRequest): Promise<FileFlow> {
  return request({
    url: `/api/v1/file-flows/${flowId}`,
    method: 'put',
    data
  })
}

/**
 * 删除文件流
 * @param flowId 文件流ID
 * @returns 删除结果
 */
export async function deleteFileFlow(flowId: string): Promise<ApiResponse<{ id: string }>> {
  return request({
    url: `/api/v1/file-flows/${flowId}`,
    method: 'delete'
  })
}

/**
 * 启动文件流
 * @param flowId 文件流ID
 * @returns 运行记录
 */
export async function startFileFlow(flowId: string): Promise<FileFlowRun> {
  return request({
    url: `/api/v1/file-flows/${flowId}/start`,
    method: 'post'
  })
}

/**
 * 停止文件流
 * @param flowId 文件流ID
 * @returns 停止结果
 */
export async function stopFileFlow(flowId: string): Promise<ApiResponse<{ id: string }>> {
  return request({
    url: `/api/v1/file-flows/${flowId}/stop`,
    method: 'post'
  })
}

/**
 * 获取文件流运行历史
 * @param flowId 文件流ID
 * @param limit 数量限制
 * @returns 运行记录列表
 */
export async function getFileFlowRuns(flowId: string, limit: number = 10): Promise<FileFlowRun[]> {
  return request({
    url: `/api/v1/file-flows/${flowId}/runs`,
    method: 'get',
    params: { limit }
  })
}

/**
 * 获取文件流统计
 * @returns 统计数据
 */
export async function getFileFlowStats(): Promise<ApiResponse<{
  total: number
  active: number
  paused: number
  error: number
  total_runs: number
  successful_runs: number
}>> {
  return request({
    url: `/api/v1/file-flows/stats`,
    method: 'get'
  })
}