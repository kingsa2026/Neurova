/**
 * 服务商管理 API 模块
 * 对应后端 /api/v1/providers
 */
import { request } from '@/api'

export interface ProviderCreateRequest {
  name: string
  provider: string    // openai / anthropic / custom (后端字段名)
  base_url: string    // API endpoint URL (后端字段名)
  api_key?: string
  description?: string
}

export interface ProviderUpdateRequest {
  name?: string
  protocol?: string
  url?: string
  base_url?: string
  api_key?: string
  description?: string
  status?: string     // active / disabled
}

export const providerAPI = {
  /** 获取所有服务商 */
  list: (enabledOnly = false) =>
    request.get(`/providers?enabled_only=${enabledOnly}`),

  /** 获取服务商统计 */
  getStats: () => request.get('/providers/stats'),

  /** 获取默认服务商 */
  getDefault: () => request.get('/providers/default'),

  /** 获取单个服务商详情 */
  get: (providerId: string) =>
    request.get(`/providers/${encodeURIComponent(providerId)}`),

  /** 创建服务商 */
  create: (data: ProviderCreateRequest) =>
    request.post('/providers', data),

  /** 更新服务商 */
  update: (providerId: string, data: ProviderUpdateRequest) =>
    request.put(`/providers/${encodeURIComponent(providerId)}`, data),

  /** 删除服务商 */
  delete: (providerId: string) =>
    request.delete(`/providers/${encodeURIComponent(providerId)}`),

  /** 测试服务商连接 */
  test: (providerId: string) =>
    request.post(`/providers/${encodeURIComponent(providerId)}/test`),

  /** 启用/禁用服务商 */
  toggle: (providerId: string, enabled: boolean) =>
    request.put(`/providers/${encodeURIComponent(providerId)}/status`, { enabled }),

  /** 搜索服务商 */
  search: (keyword: string) =>
    request.get(`/providers/search?keyword=${encodeURIComponent(keyword)}`),

  /** 设置默认服务商 */
  setDefault: (providerId: string) =>
    request.post(`/providers/${encodeURIComponent(providerId)}/set-default`),
}
