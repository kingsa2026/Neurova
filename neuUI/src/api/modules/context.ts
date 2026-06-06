import { request } from '@/api'

// 构建上下文请求
export interface BuildContextRequest {
  agent_id?: string
  user_input?: string
  session_id?: string
  max_tokens?: number
  include_reflection?: boolean
  include_memories?: boolean
  include_constitution?: boolean
  metadata?: Record<string, any>
}

// 构建上下文响应
export interface BuildContextResponse {
  context_id: string
  content: string
  token_count: number
  sources: string[]
  build_time: number
}

// 上下文统计
export interface ContextStats {
  total_contexts: number
  average_tokens: number
  cache_hit_rate: number
  compression_rate: number
}

// 上下文预览
export interface ContextPreview {
  context_id: string
  content: string
  token_count: number
  sources: string[]
}

/**
 * 构建上下文
 * @param data 构建上下文请求
 * @returns 构建结果
 */
export async function buildContext(data: BuildContextRequest = {}): Promise<BuildContextResponse> {
  return request({
    url: '/api/v1/context/build',
    method: 'post',
    data,
  })
}

/**
 * 构建上下文 v2
 * @param data 构建上下文请求
 * @returns 构建结果
 */
export async function buildContextV2(data: BuildContextRequest = {}): Promise<BuildContextResponse> {
  return request({
    url: '/api/v1/context/build/v2',
    method: 'post',
    data,
  })
}

/**
 * 获取上下文统计
 * @returns 统计信息
 */
export async function getContextStats(): Promise<ContextStats> {
  return request({
    url: '/api/v1/context/stats',
    method: 'get',
  })
}

/**
 * 获取上下文预览
 * @param contextId 上下文ID
 * @returns 预览信息
 */
export async function getContextPreview(contextId: string): Promise<ContextPreview> {
  return request({
    url: `/api/v1/context/${contextId}/preview`,
    method: 'get',
  })
}

/**
 * 压缩上下文
 * @param contextId 上下文ID
 * @returns 压缩结果
 */
export async function compressContext(contextId: string): Promise<{ success: boolean; compressed_size: number }> {
  return request({
    url: `/api/v1/context/${contextId}/compress`,
    method: 'post',
  })
}

/**
 * 注入反思日志
 * @param data 注入参数
 * @returns 注入结果
 */
export async function injectReflection(data: { context_id: string; reflection_logs: string[] }): Promise<{ success: boolean }> {
  return request({
    url: '/api/v1/context/inject/reflection',
    method: 'get',
    params: data,
  })
}

/**
 * 注入记忆
 * @param data 注入参数
 * @returns 注入结果
 */
export async function injectMemories(data: { context_id: string; memory_ids: string[] }): Promise<{ success: boolean }> {
  return request({
    url: '/api/v1/context/inject/memories',
    method: 'get',
    params: data,
  })
}

/**
 * 注入高温记忆
 * @param data 注入参数
 * @returns 注入结果
 */
export async function injectHotMemories(data: { context_id: string; hot_memory_threshold: number }): Promise<{ success: boolean }> {
  return request({
    url: '/api/v1/context/inject/hot',
    method: 'get',
    params: data,
  })
}

export default {
  buildContext,
  buildContextV2,
  getContextStats,
  getContextPreview,
  compressContext,
  injectReflection,
  injectMemories,
  injectHotMemories,
}