/**
 * Open Platform API Module
 * 开放平台 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface ApiKey {
  id: string
  name: string
  key: string
  permissions: string[]
  rate_limit: number
  created_at: number
  last_used?: number
  expires_at?: number
}

export interface CreateApiKeyRequest {
  name: string
  permissions?: string[]
  rate_limit?: number
  expires_in_days?: number
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取 API Key 列表
 * @returns API Key 列表
 */
export async function getApiKeys(): Promise<ApiKey[]> {
  return request({ url: `/api/v1/openplatform/api-keys`, method: 'get' })
}

/**
 * 创建 API Key
 * @param data API Key 数据
 * @returns 创建的 API Key
 */
export async function createApiKey(data: CreateApiKeyRequest): Promise<ApiKey> {
  return request({ url: `/api/v1/openplatform/api-keys`, method: 'post', data })
}

/**
 * 删除 API Key
 * @param keyId API Key ID
 * @returns 删除结果
 */
export async function deleteApiKey(keyId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/openplatform/api-keys/${keyId}`, method: 'delete' })
}

/**
 * 验证 API Key
 * @param apiKey API Key
 * @returns 验证结果
 */
export async function validateApiKey(apiKey: string): Promise<ApiResponse<{ valid: boolean; permissions: string[] }>> {
  return request({ url: `/api/v1/openplatform/validate`, method: 'post', params: { api_key: apiKey } })
}

/**
 * 获取 API 调用统计
 * @param apiKeyId API Key ID
 * @param period 时间范围
 * @returns 调用统计
 */
export async function getApiKeyUsageStats(apiKeyId: string, period: string = 'day'): Promise<ApiResponse<{
  total_calls: number
  successful_calls: number
  failed_calls: number
  avg_response_time: number
}>> {
  return request({ url: `/api/v1/openplatform/api-keys/${apiKeyId}/stats`, method: 'get', params: { period } })
}

/**
 * 获取 API 文档
 * @returns API 文档
 */
export async function getApiDocs(): Promise<ApiResponse<{ version: string; endpoints: any[] }>> {
  return request({ url: `/api/v1/openplatform/docs`, method: 'get' })
}

/**
 * 获取 Webhook 列表
 * @returns Webhook 列表
 */
export async function getWebhooks(): Promise<any[]> {
  return request({ url: `/api/v1/openplatform/webhooks`, method: 'get' })
}

/**
 * 创建 Webhook
 * @param url Webhook URL
 * @param events 事件类型
 * @returns 创建的 Webhook
 */
export async function createWebhook(url: string, events: string[]): Promise<any> {
  return request({ url: `/api/v1/openplatform/webhooks`, method: 'post', data: { url, events } })
}

/**
 * 删除 Webhook
 * @param webhookId Webhook ID
 * @returns 删除结果
 */
export async function deleteWebhook(webhookId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/openplatform/webhooks/${webhookId}`, method: 'delete' })
}

/**
 * 测试 Webhook
 * @param webhookId Webhook ID
 * @returns 测试结果
 */
export async function testWebhook(webhookId: string): Promise<ApiResponse<{ success: boolean; response_code: number }>> {
  return request({ url: `/api/v1/openplatform/webhooks/${webhookId}/test`, method: 'post' })
}