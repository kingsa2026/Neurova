import { request } from '@/api'

export const modelAPI = {
  /** 获取所有可用模型 */
  list: () => request.get('/models'),

  /** 获取所有服务商 */
  getProviders: () => request.get('/models/providers'),

  /** 获取当前活跃模型 */
  getCurrent: () => request.get('/models/current'),

  /** 获取模型统计 */
  getStats: () => request.get('/models/stats'),

  /** 添加模型到指定服务商 */
  add: (data: {
    provider_id: string
    model_name: string
    model_display_name?: string
    description?: string
    max_tokens?: number
    capabilities?: string[]
  }) => request.post('/models', data),

  /** 从服务商删除模型 */
  remove: (providerId: string, modelName: string) =>
    request.delete(`/models/${providerId}/${encodeURIComponent(modelName)}`),

  /** 删除整个服务商 */
  removeProvider: (providerId: string) =>
    request.delete(`/models/${providerId}`),

  /** 切换当前活跃模型 */
  switch: (providerId: string, model: string) =>
    request.post('/models/switch', { provider_id: providerId, model }),

  /** 内容感知自动选择最佳模型 */
  autoDetect: (data: {
    content_types: string[]
    message_text?: string
    preferred_model?: string
    auto_switch?: boolean
  }) => request.post('/models/auto-detect', data),

  /** 获取模型详情（含能力标签） */
  getModelDetail: (providerId: string, model: string) =>
    request.get(`/models/${encodeURIComponent(providerId)}/${encodeURIComponent(model)}`),

  /** 更新模型配置（如能力标签、max_tokens） */
  updateModel: (providerId: string, modelName: string, data: {
    model_display_name?: string
    description?: string
    max_tokens?: number
    capabilities?: string[]
  }) => request.put(`/models/${encodeURIComponent(providerId)}/${encodeURIComponent(modelName)}`, data),

  /** 检测并持久化模型多模态能力 */
  detectCapability: (providerId: string, model?: string) =>
    request.post('/models/capabilities', {
      provider_id: providerId,
      ...(model ? { model } : {}),
    }),

  /** 获取已持久化的模型能力 */
  getCapabilities: (providerId: string) =>
    request.get(`/models/capabilities/${encodeURIComponent(providerId)}`),
}
